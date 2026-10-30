"""Regras de envio dos alertas.

- Uma mensagem por acontecimento. Opcional (lembrete_critico): enquanto um crítico continua,
  manda um LEMBRETE a cada N min (sem repetir o print) até o "ok" ou até o limite.
- Aviso: uma vez.
- Intervalo mínimo (cooldown): mesmo alerta do mesmo slot no máximo 1× a cada 5 min.
- Agrupamento: alertas do mesmo ciclo saem numa mensagem só.
- Horário silencioso (só para canais externos), com opção de deixar críticos passarem.
- Pausa: suspende os envios até retomar (ou até o fim do tempo pedido).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .config import Config

log = logging.getLogger(__name__)

SEV_LABEL = {"critico": "CRÍTICO", "aviso": "AVISO", "info": "OK"}
SEV_ORDER = {"info": 0, "aviso": 1, "critico": 2}


@dataclass
class Alert:
    slot: int | None
    kind: str
    severity: str  # critico | aviso | info
    title: str
    header: str = ""  # 'Slot 2 "Elf Kanturu" (Kanturu 213,39)'
    detail: str = ""
    ts: float = field(default_factory=time.time)
    repeats: int = 0
    last_sent: float = 0.0
    acked: bool = False
    image: bytes | None = field(default=None, repr=False)  # print da janela (JPEG) para quem aceita imagem
    first_ts: float = 0.0  # quando aconteceu (o ts muda nos lembretes)

    @property
    def key(self) -> tuple[int | None, str]:
        return (self.slot, self.kind)

    def render(self, level: int, inbound: bool, reminders: bool = False) -> str:
        sev = f"[{SEV_LABEL[self.severity]}] "
        head = f" - {self.header}" if self.header else ""
        if self.repeats:  # lembrete: deixa claro que é o mesmo acontecimento, não um novo
            since = self.first_ts or self.ts
            mins = max(0, int((self.ts - since) // 60))
            line1 = f"{sev}LEMBRETE: {self.title} continua{head} (lembrete {self.repeats})"
            line2 = " · ".join((f"desde {time.strftime('%H:%M', time.localtime(since))} (há {mins} min)",
                                f"nível {level}"))
        else:
            line1 = f"{sev}{self.title}{head}"
            line2 = " · ".join(p for p in (time.strftime("%H:%M", time.localtime(self.ts)), self.detail,
                                           f"nível {level}") if p)
        lines = [line1, line2]
        if inbound and self.severity == "critico" and self.slot:
            lines.append(f"Responda /ok para parar os lembretes · /print {self.slot} para ver a tela" if reminders
                         else f"Responda /print {self.slot} para ver a tela agora")
        return "\n".join(lines)


def in_quiet_hours(cfg: Config, now: float) -> bool:
    q = cfg.alerts.quiet
    if not q.enabled:
        return False
    t = time.localtime(now)
    cur = t.tm_hour * 60 + t.tm_min
    sh, sm = map(int, q.start.split(":"))
    eh, em = map(int, q.end.split(":"))
    start, end = sh * 60 + sm, eh * 60 + em
    if start == end:
        return False
    return start <= cur < end if start < end else (cur >= start or cur < end)


class AlertManager:
    def __init__(self, config: Config, notifiers: list, clock: Callable[[], float] = time.time,
                 level: Callable[[], int] = lambda: 0, on_sent: Callable[[str, Alert], None] | None = None) -> None:
        self.cfg = config
        self.notifiers = list(notifiers)
        self.clock = clock
        self.level = level
        self.on_sent = on_sent
        self._lock = threading.RLock()
        self._pending: list[Alert] = []
        self._last_by_key: dict[tuple, float] = {}
        self.active: dict[tuple, Alert] = {}  # críticos aguardando "ok"
        self.paused_until: float | None = None  # float('inf') = até retomar

    # ------------------------------------------------------------------
    def set_notifiers(self, notifiers: list) -> None:
        with self._lock:
            self.notifiers = list(notifiers)

    def submit(self, alert: Alert) -> bool:
        """Entra na fila do ciclo. False = descartado pelo intervalo mínimo."""
        with self._lock:
            now = self.clock()
            alert.ts = alert.first_ts = now
            last = self._last_by_key.get(alert.key)
            if alert.severity != "info" and last is not None and now - last < self.cfg.alerts.cooldown_min * 60:
                log.info("alerta %s do slot %s ignorado (intervalo mínimo)", alert.kind, alert.slot)
                return False
            if alert.severity != "info":
                self._last_by_key[alert.key] = now
            self._pending.append(alert)
            if alert.severity == "critico":
                self.active[alert.key] = alert
            return True

    def resolve(self, slot: int | None, kinds: set[str] | None = None) -> list[Alert]:
        """O problema passou: para de repetir. Retorna os críticos que estavam ativos."""
        with self._lock:
            gone = [k for k in self.active if k[0] == slot and (kinds is None or k[1] in kinds)]
            return [self.active.pop(k) for k in gone]

    def ack(self, slot: int | None = None) -> int:
        """Reconhece ('ok') os críticos ativos (de um slot ou todos)."""
        with self._lock:
            keys = [k for k in self.active if slot is None or k[0] == slot]
            for k in keys:
                self.active.pop(k).acked = True
            return len(keys)

    def pause(self, minutes: float | None = None) -> None:
        with self._lock:
            self.paused_until = float("inf") if minutes is None else self.clock() + minutes * 60

    def resume(self) -> None:
        with self._lock:
            self.paused_until = None

    @property
    def paused(self) -> bool:
        if self.paused_until is None:
            return False
        if self.clock() >= self.paused_until:
            self.paused_until = None
            return False
        return True

    # ------------------------------------------------------------------
    def flush(self) -> None:
        """Envia o que entrou neste ciclo (agrupado) e as repetições vencidas."""
        with self._lock:
            now = self.clock()
            batch, self._pending = self._pending, []
            batch += self._due_repeats(now)
            if not batch:
                return
            if self.paused:
                log.info("alertas pausados: %d não enviados", len(batch))
                return
            for a in batch:
                a.last_sent = now
            self._dispatch(batch, now)

    def _due_repeats(self, now: float) -> list[Alert]:
        if not self.cfg.alerts.repeat_critical:
            return []
        out = []
        inbound = any(getattr(n, "supports_inbound", False) for n in self.notifiers)
        limit = None if inbound else self.cfg.alerts.max_repeats_no_reply
        for a in self.active.values():
            if a.last_sent == 0:  # ainda não saiu nenhuma vez
                continue
            if limit is not None and a.repeats >= limit:
                continue
            if now - a.last_sent >= self.cfg.alerts.critical_repeat_min * 60:
                a.repeats += 1
                a.ts = now
                out.append(a)
        return out

    def _dispatch(self, batch: list[Alert], now: float) -> None:
        quiet = in_quiet_hours(self.cfg, now)
        for n in self.notifiers:
            items = batch
            if quiet and getattr(n, "external", True):
                items = [a for a in batch if a.severity == "critico" and self.cfg.alerts.quiet.allow_critical]
            if not items:
                continue
            text = self.compose(items, getattr(n, "supports_inbound", False))
            image = None
            if getattr(n, "supports_images", False):  # lembrete não repete o print
                image = next((a.image for a in items if a.image and not a.repeats), None)
            try:
                n.send(text, image) if image else n.send(text)
            except Exception:
                log.exception("notificador %s falhou", getattr(n, "name", n))
        for a in batch:
            if self.on_sent:
                self.on_sent("silencioso" if quiet else "enviado", a)

    def compose(self, items: list[Alert], inbound: bool = False) -> str:
        level = self.level()
        rem = self.cfg.alerts.repeat_critical
        if len(items) == 1:
            return items[0].render(level, inbound, rem)
        worst = max(items, key=lambda a: SEV_ORDER[a.severity]).severity
        head = f"[{SEV_LABEL[worst]}] {len(items)} alertas ao mesmo tempo"
        return head + "\n\n" + "\n\n".join(a.render(level, inbound, rem) for a in items)
