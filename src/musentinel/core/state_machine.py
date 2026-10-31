"""Máquina de estados de um slot.

Entrada: uma Observation por ciclo (saúde + leitura do HUD). Saída: estado
confirmado e sinais (alertas candidatos). Sem Qt, sem Windows: testável sozinha.

Regras principais:
- um estado novo só vale depois de N ciclos seguidos iguais (ciclos_confirmacao);
- ILEGÍVEL nunca gera alerta crítico (menu aberto, janela coberta, loading);
- morte "trava" (latch) até a caça voltar: renascer na cidade com HP cheio continua MORTO;
- TRAVADO é só o Windows dizer "Não respondendo": imagem parada não conta (a Loja e um
  personagem parado na cidade ficam com a imagem igual e estão normais);
- leitura de HP com máximo diferente do de sempre é erro de leitura (não conta para morte/HP baixo);
- avisos que você mesmo causa no PC (Helper pausado, menu aberto) esperam você sair do PC.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from .config import Config


class State(str, Enum):
    ONLINE = "ONLINE"  # lendo o HUD, ainda sem saber se está caçando
    CACANDO = "CAÇANDO"
    PARADO = "PARADO"
    MORTO = "MORTO"
    DESCONECTADO = "DESCONECTADO"
    TRAVADO = "TRAVADO"
    FECHADO = "FECHADO"
    ILEGIVEL = "ILEGÍVEL"


HP_MAX_STABLE_READS = 3  # mesmo HP máximo em 3 leituras = o máximo de verdade do personagem
HP_LOW_EVERY_S = 900  # HP baixo: no máximo 1 aviso a cada 15 min (o HP sobe e desce na caça)
CRITICAL ={State.MORTO, State.DESCONECTADO, State.TRAVADO, State.FECHADO}
ALERT_TITLE = {
    State.MORTO: "MORTE",
    State.DESCONECTADO: "DESCONECTADO",
    State.TRAVADO: "JANELA TRAVADA",
    State.FECHADO: "CLIENT FECHADO",
}


@dataclass
class Observation:
    ts: float
    process_alive: bool = True
    hung: bool = False  # o Windows marcou a janela como "Não respondendo"
    capture_ok: bool = True
    capture_note: str = ""
    connected: bool | None = None  # None = desconhecido (sem referência, ou trocando de servidor)
    user_active: bool = False  # usuário mexeu no PC há pouco (ida manual à cidade, menu, Helper pausado)
    hp: tuple[int, int] | None = None
    exp: tuple[int, int] | None = None
    coords: tuple[int, int] | None = None
    map: str | None = None
    hunting_time: int | None = None  # segundos; None = painel fechado/ilegível
    note: str = ""  # por que está ilegível


@dataclass
class Signal:
    kind: str  # MORTO, DESCONECTADO, ..., PARADO, ILEGIVEL, HELPER, HP_BAIXO, RESOLVIDO
    severity: str  # critico | aviso | info
    title: str
    detail: str = ""
    state: State | None = None
    previous: State | None = None


@dataclass
class SlotView:
    """O que a GUI e os alertas precisam saber do slot."""

    state: State = State.ONLINE
    since: float = 0.0
    hp: tuple[int, int] | None = None
    exp: tuple[int, int] | None = None
    coords: tuple[int, int] | None = None
    map: str | None = None
    exp_per_h: float | None = None
    exp_pct_per_h: float | None = None
    hunting_time: int | None = None
    note: str = ""
    last_hunting_map: str | None = None
    hunting_since: float | None = None


class ExpRate:
    """EXP/h na janela dos últimos N minutos (soma subidas; trata subida de nível)."""

    def __init__(self, window_s: float = 600) -> None:
        self.window_s = window_s
        self.samples: deque[tuple[float, int, int]] = deque()

    def add(self, ts: float, cur: int, mx: int) -> None:
        if self.samples and self.samples[-1][1:] == (cur, mx):
            return
        self.samples.append((ts, cur, mx))
        while self.samples and ts - self.samples[0][0] > self.window_s:
            self.samples.popleft()

    def rate(self, now: float) -> tuple[float | None, float | None]:
        if len(self.samples) < 2:
            return None, None
        gained = 0.0
        pct = 0.0
        for (_, c0, m0), (_, c1, m1) in zip(self.samples, list(self.samples)[1:]):
            if m1 == m0:
                d = c1 - c0
                if d > 0:
                    gained += d
                    pct += d / m0
            else:  # subiu de nível: terminou o nível anterior e começou o novo
                gained += max(0, m0 - c0) + c1
                pct += max(0, m0 - c0) / m0 + c1 / m1
        span = now - self.samples[0][0]
        if span < 60:
            return None, None
        return gained * 3600 / span, pct * 100 * 3600 / span


class SlotTracker:
    def __init__(self, slot: int, config: Config) -> None:
        self.slot = slot
        self.cfg = config
        self.view = SlotView()
        self._candidate: State | None = None
        self._candidate_n = 0
        self._started: float | None = None
        self._hung_since: float | None = None
        self._unreadable_since: float | None = None
        self._unreadable_warned = False
        self._hp_zero = 0
        self._dead = False
        self._dead_reason = ""
        self._last_exp: tuple[int, int] | None = None
        self._last_exp_rise: float | None = None
        self._last_ht: int | None = None
        self._last_ht_ts: float | None = None
        self._last_ht_rise: float | None = None
        self._helper_warned = False
        self._helper_was_running = False
        self._hp_max: int | None = None  # HP máximo confirmado (filtra leituras erradas)
        self._hp_max_cand: int | None = None
        self._hp_max_n = 0
        self._hp_low_n = 0
        self._hp_low_warned = False
        self._hp_low_at: float | None = None
        self._last_map: str | None = None
        self._ht_pending: tuple[int, float] | None = None
        self._hp_now: tuple[int, int] | None = None  # HP deste ciclo, se a leitura é confiável
        self._rate = ExpRate()

    # ------------------------------------------------------------------
    def update(self, o: Observation) -> list[Signal]:
        th = self.cfg.thresholds
        if self._started is None:
            self._started = o.ts
            self.view.since = o.ts
        signals: list[Signal] = []

        self._track_readings(o)
        raw = self._raw_state(o)

        # sinais que não dependem de mudança de estado
        signals += self._side_signals(o, raw)

        # confirmação: N ciclos seguidos iguais
        if raw == self.view.state:
            self._candidate, self._candidate_n = None, 0
        else:
            if raw == self._candidate:
                self._candidate_n += 1
            else:
                self._candidate, self._candidate_n = raw, 1
            if self._candidate_n >= self.cfg.monitor.confirm_cycles:
                signals += self._transition(raw, o)

        # ILEGÍVEL prolongado: aviso (nunca crítico), só com você longe do PC (perto, foi você que abriu o menu)
        if self.view.state == State.ILEGIVEL and not o.user_active:
            if self._unreadable_since and not self._unreadable_warned and \
                    o.ts - self._unreadable_since >= th.unreadable_warn_min * 60:
                self._unreadable_warned = True
                signals.append(Signal("ILEGIVEL", "aviso", "LEITURA ILEGÍVEL",
                                      f"HUD ilegível há {th.unreadable_warn_min:g} min ({o.note or 'menu/janela por cima?'})"))
        self.view.note = o.note
        return signals

    # ------------------------------------------------------------------
    def _hp_trusted(self, hp: tuple[int, int]) -> bool:
        """HP com o máximo de sempre. '0/28' com máximo 208 é erro de leitura, não morte."""
        cur, mx = hp
        if cur > 0:  # o máximo muda com o personagem vivo (subiu de nível, buff); morto mostra 0/máximo de antes
            if mx == self._hp_max_cand:
                self._hp_max_n += 1
            else:
                self._hp_max_cand, self._hp_max_n = mx, 1
            if self._hp_max_n >= HP_MAX_STABLE_READS:
                self._hp_max = mx
        return 0 <= cur <= mx and (self._hp_max is None or mx == self._hp_max)

    def _track_ht(self, value: int, ts: float) -> None:
        """Hunting Time: aceita só leituras que batem com o tempo que passou (um dígito lido errado
        não pode fingir que o Helper parou ou andou)."""
        def fits(base: int, base_ts: float) -> bool:
            return base <= value <= base + (ts - base_ts) * 1.5 + 10

        if self._last_ht is None or self._last_ht_ts is None or fits(self._last_ht, self._last_ht_ts):
            if self._last_ht is not None and value > self._last_ht:
                self._last_ht_rise = ts
        elif self._ht_pending is not None and fits(*self._ht_pending):
            # duas leituras seguidas concordam entre si: o Helper reiniciou (ou a anterior estava errada)
            if value > self._ht_pending[0]:
                self._last_ht_rise = ts
        else:
            self._ht_pending = (value, ts)  # fora do esperado: espera a próxima confirmar
            return
        self._last_ht, self._last_ht_ts, self._ht_pending = value, ts, None

    def _track_readings(self, o: Observation) -> None:
        v = self.view
        shop = self.cfg.is_shop(self.slot)
        self._hp_now = o.hp if o.hp is not None and self._hp_trusted(o.hp) else None
        if self._hp_now is not None:
            v.hp = self._hp_now
        if o.coords is not None:
            v.coords = o.coords
        if o.map is not None:
            v.map = o.map
        v.hunting_time = o.hunting_time

        if o.exp is not None:
            if self._last_exp is not None:
                (c0, m0), (c1, m1) = self._last_exp, o.exp
                if (m1 == m0 and c1 > c0) or m1 != m0:  # subiu, ou subiu de nível
                    self._last_exp_rise = o.ts
            self._last_exp = o.exp
            v.exp = o.exp
            self._rate.add(o.ts, *o.exp)
        v.exp_per_h, v.exp_pct_per_h = self._rate.rate(o.ts)

        if o.hunting_time is not None:
            self._track_ht(o.hunting_time, o.ts)

        # morte por HP 0 (a Loja fica na cidade, onde não se morre: HP 0 lá é erro de leitura)
        hp = self._hp_now
        if hp is not None and not shop:
            self._hp_zero = self._hp_zero + 1 if hp[0] == 0 else 0
            if self._hp_zero >= self.cfg.thresholds.death_hp_reads:
                if not self._dead:
                    self._dead_reason = f"HP {hp[0]}/{hp[1]}"
                self._dead = True

        # morte por ida à cidade vinda da caça, sem o usuário ter mexido
        left_city = False
        if o.map is not None:
            prev = self._last_map
            left_city = prev is not None and self.cfg.is_city(prev) and not self.cfg.is_city(o.map)
            self._last_map = o.map
            if (prev is not None and o.map != prev and self.cfg.is_city(o.map)
                    and not self.cfg.is_city(prev) and self.view.state == State.CACANDO
                    and not o.user_active and not shop):
                if not self._dead:
                    self._dead_reason = f"foi de {prev} para {o.map} sem comando"
                self._dead = True

        # morte só "destrava" com sinal claro de vida: EXP subiu agora, ou saiu da cidade
        if self._dead and hp is not None and hp[0] > 0:
            if self._last_exp_rise == o.ts and o.exp is not None:
                self._dead = False
            elif left_city:
                self._dead = False

    def _progressing(self, now: float) -> bool:
        th = self.cfg.thresholds
        exp_ok = self._last_exp_rise is not None and now - self._last_exp_rise < th.exp_stall_min * 60
        ht_ok = self._last_ht_rise is not None and now - self._last_ht_rise < th.helper_stall_s
        return exp_ok or ht_ok

    def _raw_state(self, o: Observation) -> State:
        th = self.cfg.thresholds
        if not o.process_alive:
            return State.FECHADO
        if o.hung:
            self._hung_since = self._hung_since or o.ts
        else:
            self._hung_since = None
        if self._hung_since is not None and o.ts - self._hung_since >= th.hung_s:
            return State.TRAVADO  # o Windows diz "Não respondendo" (imagem parada sozinha não é travamento)
        if o.connected is False:
            return State.DESCONECTADO
        if self._dead:
            return State.MORTO
        readable = o.capture_ok and (o.hp is not None or o.exp is not None)
        if not readable:
            self._unreadable_since = self._unreadable_since or o.ts
            return State.ILEGIVEL
        self._unreadable_since = None
        self._unreadable_warned = False
        if self.cfg.is_shop(self.slot):
            return State.ONLINE  # personagem da loja fica parado na cidade de propósito
        ref = self._last_exp_rise or self._started or o.ts
        if o.ts - ref >= th.exp_stall_min * 60:
            return State.PARADO  # sem EXP há N min, mesmo com o Hunting Time contando
        if self._progressing(o.ts):
            return State.CACANDO
        # sem evidência de caça ainda: mantém CAÇANDO/PARADO se já estava, senão ONLINE
        if self.view.state in (State.CACANDO, State.PARADO):
            return self.view.state
        return State.ONLINE

    def _side_signals(self, o: Observation, raw: State) -> list[Signal]:
        th = self.cfg.thresholds
        out: list[Signal] = []
        online = raw in (State.CACANDO, State.PARADO, State.ONLINE)
        shop = self.cfg.is_shop(self.slot)
        # Helper parou: Hunting Time subia e parou (painel aberto e legível).
        # Com você mexendo no PC, espera: pausar o Helper na mão não é problema; avisa se continuar
        # parado depois que você sair.
        if o.hunting_time is not None and online and not shop:
            running = self._last_ht_rise is not None and o.ts - self._last_ht_rise < th.helper_stall_s
            if running:
                self._helper_was_running = True
                self._helper_warned = False
            elif self._helper_was_running and not self._helper_warned and self._last_ht_rise is not None \
                    and not o.user_active:
                self._helper_warned = True
                self._helper_was_running = False
                out.append(Signal("HELPER", "aviso", "HELPER PAROU",
                                  f"Hunting Time parado há {_ago(o.ts - self._last_ht_rise)}"))
        # HP baixo (aviso preventivo): 2 leituras seguidas abaixo do limite, no máximo 1 a cada 15 min
        hp = self._hp_now
        if hp is not None and hp[1] > 0 and online and not self._dead and not shop:
            pct = 100 * hp[0] / hp[1]
            if 0 < pct < th.hp_low_pct:
                self._hp_low_n += 1
                recent = self._hp_low_at is not None and o.ts - self._hp_low_at < HP_LOW_EVERY_S
                if self._hp_low_n >= 2 and not self._hp_low_warned and not recent:
                    self._hp_low_warned = True
                    self._hp_low_at = o.ts
                    out.append(Signal("HP_BAIXO", "aviso", "HP BAIXO", f"HP {hp[0]}/{hp[1]} ({pct:.0f}%)"))
            else:
                self._hp_low_n = 0
                if pct >= th.hp_low_pct + 10:
                    self._hp_low_warned = False
        return out

    def _transition(self, new: State, o: Observation) -> list[Signal]:
        old = self.view.state
        v = self.view
        if old == State.CACANDO:
            v.last_hunting_map = v.map if not self.cfg.is_city(v.map) else v.last_hunting_map
        hunting_for = (o.ts - v.hunting_since) if (old == State.CACANDO and v.hunting_since) else None
        v.state = new
        v.since = o.ts
        self._candidate, self._candidate_n = None, 0
        if new == State.CACANDO:
            v.hunting_since = o.ts
        out: list[Signal] = []
        detail = self._detail(new, o, old, hunting_for)
        if new in CRITICAL:
            out.append(Signal(new.name, "critico", ALERT_TITLE[new], detail, new, old))
        elif new == State.PARADO and old == State.CACANDO:
            out.append(Signal("PARADO", "aviso", "CAÇA PARADA", detail, new, old))
        if old in CRITICAL and new not in CRITICAL and new != State.ILEGIVEL:
            out.append(Signal("RESOLVIDO", "info", f"{ALERT_TITLE[old]} RESOLVIDO",
                              f"agora {new.value}", new, old))
        if new == State.FECHADO:
            self._dead = False
        return out

    def _detail(self, new: State, o: Observation, old: State, hunting_for: float | None) -> str:
        parts: list[str] = []
        if new == State.MORTO:
            parts.append(self._dead_reason)
        elif new == State.DESCONECTADO:
            parts.append("conexão com o servidor fechou")
        elif new == State.TRAVADO:
            since = (o.ts - self._hung_since) if self._hung_since else 0
            parts.append(f'o Windows marcou a janela como "Não respondendo" há {_ago(since)}')
        elif new == State.FECHADO:
            parts.append("processo do jogo não existe mais")
        elif new == State.PARADO:
            ref = self._last_exp_rise
            parts.append(f"sem EXP há {(o.ts - ref) / 60:.0f} min" if ref else "sem EXP")
        if self.view.hp and new != State.MORTO:
            parts.append(f"HP {self.view.hp[0]}/{self.view.hp[1]}")
        if hunting_for is not None:
            parts.append(f"estava {old.value} há {hunting_for / 60:.0f} min")
        elif old != new:
            parts.append(f"antes: {old.value}")
        return " · ".join(p for p in parts if p)

    # ------------------------------------------------------------------
    def reset_process(self) -> None:
        """Client reaberto (PID novo): esquece morte/progresso do processo antigo."""
        self._dead = False
        self._hp_zero = 0
        self._last_exp = None
        self._last_ht = self._last_ht_ts = self._ht_pending = None
        self._helper_was_running = False
        self._last_map = None
        self._hung_since = None
        self._hp_max = self._hp_max_cand = None
        self._hp_max_n = 0
        self._rate = ExpRate()


def _ago(seconds: float) -> str:
    """45 → '45 s'; 150 → '2 min'."""
    return f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60:.0f} min"


@dataclass
class GeneralOutage:
    """Queda geral: 2+ slots desconectados no mesmo ciclo."""

    slots: list[int] = field(default_factory=list)
