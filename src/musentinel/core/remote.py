"""Pedidos feitos pelo celular (Telegram): status, print e os painéis abertos no jogo.

Nada aqui mexe no jogo: os comandos só leem a imagem das janelas e controlam os alertas do
próprio MU Sentinel (ok / pausar / retomar). Os painéis precisam estar abertos pelo usuário.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass

from .panels import jpeg
from .perception import panels as P

log = logging.getLogger(__name__)


@dataclass
class Command:
    name: str
    slot: int | None = None
    arg: str = ""


@dataclass
class Reply:
    text: str
    image: bytes | None = None


# primeira palavra (sem acento, minúscula, sem / e sem emoji) → comando
ALIASES = {
    "status": "status", "estado": "status", "slots": "status",
    "print": "print", "foto": "print", "tela": "print",
    "inventario": "inventario", "inv": "inventario", "i": "inventario", "bolsa": "inventario",
    "personagem": "personagem", "char": "personagem", "c": "personagem", "pontos": "personagem",
    "cacada": "caca", "caca": "caca", "hunting": "caca", "tempo": "caca",
    "loja": "loja", "gremory": "loja", "vendas": "loja",
    "ok": "ok", "vi": "ok",
    "pausar": "pausar", "pausa": "pausar",
    "retomar": "retomar", "voltar": "retomar",
    "ajuda": "ajuda", "help": "ajuda", "start": "ajuda", "menu": "ajuda", "comandos": "ajuda",
}

KEYBOARD = [["📊 Status", "📸 Print"], ["🎒 Inventário", "🧍 Personagem"], ["⏱ Caçada", "🏪 Loja"],
            ["✅ OK, vi o alerta"]]

BOT_COMMANDS = [  # menu "/" do Telegram (só letras minúsculas, dígitos e _)
    ("status", "Como estão os slots"),
    ("print", "Print da janela (ex.: /print 2)"),
    ("inventario", "Inventário (I): imagem, espaços e Zen"),
    ("personagem", "Janela C: level e pontos"),
    ("cacada", "Instant Hunting Log: tempo e EXP/h"),
    ("loja", "Gremory Case da janela Loja"),
    ("ok", "Marcar os alertas críticos como vistos"),
    ("pausar", "Pausar os alertas (ex.: /pausar 60)"),
    ("retomar", "Retomar os alertas"),
    ("ajuda", "O que dá para pedir"),
]

HELP = """MU Sentinel — o que dá para pedir (use os botões ou digite):
/status — como estão os slots
/print 2 — print da janela do slot 2 (sem número: todos)
/inventario 2 — Inventário (I): imagem, espaços livres e Zen
/personagem 2 — janela C: level, pontos a distribuir, atributos
/cacada 2 — Instant Hunting Log: tempo de caça, EXP/h, abates
/loja — Gremory Case do slot Loja (vendas)
/ok — marca os alertas críticos como vistos (para os lembretes, se ligados)
/pausar 60 — pausa os alertas por 60 min · /retomar

Os painéis precisam estar abertos no jogo: o MU Sentinel só olha a tela, não aperta teclas."""


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def parse(text: str) -> Command | None:
    """'/inventario 2', 'inv 2', '🎒 Inventário', '/print@MeuBot 3', 'ok' → Command."""
    raw = (text or "").strip()
    if not raw:
        return None
    first, _, rest = raw.partition(" ")
    if first.startswith("/") and "@" in first:  # /comando@NomeDoBot
        first = first.split("@", 1)[0]
        raw = f"{first} {rest}".strip()
    words = _plain(raw).split()
    if not words:
        return None
    name = ALIASES.get(words[0])
    if name is None:
        return None
    nums = [int(w) for w in words[1:] if w.isdigit()]
    slot = nums[0] if nums else None
    return Command(name, slot, " ".join(words[1:]))


def _ago(ts: float, now: float) -> str:
    m = int(max(0, now - ts) // 60)
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


class RemoteCommands:
    """Responde aos comandos usando o motor (engine) do app."""

    PANEL_CMDS = ("inventario", "personagem", "caca", "loja")

    def __init__(self, engine, clock=time.time) -> None:
        self.engine = engine
        self.clock = clock

    def handle(self, cmd: Command) -> list[Reply]:
        try:
            if cmd.name == "ajuda":
                return [Reply(HELP)]
            if cmd.name == "status":
                return [Reply(self._status())]
            if cmd.name == "print":
                return self._prints(cmd.slot)
            if cmd.name in self.PANEL_CMDS:
                return self._panel(cmd.name, cmd.slot)
            if cmd.name == "ok":
                n = self.engine.ack()
                return [Reply(f"✅ {n} alerta(s) marcado(s) como visto(s)." if n
                              else "Nenhum alerta crítico em aberto agora.")]
            if cmd.name == "pausar":
                mins = cmd.slot if cmd.slot else 60
                self.engine.pause_alerts(float(mins))
                return [Reply(f"⏸ Alertas pausados por {mins} min. Mande /retomar para voltar antes.")]
            if cmd.name == "retomar":
                self.engine.resume_alerts()
                return [Reply("▶ Alertas retomados.")]
        except Exception as exc:  # um pedido nunca derruba o app
            log.exception("erro no comando %s", cmd.name)
            return [Reply(f"Não consegui atender o pedido ({type(exc).__name__}). Detalhes no log do app.")]
        return [Reply(HELP)]

    # ------------------------------------------------------------------
    def _header(self, n: int) -> str:
        return f'Slot {n} "{self.engine.cfg.slot_name(n)}"'

    def _targets(self, slot: int | None) -> tuple[list[int], str | None]:
        nums = [s.slot for s in self.engine.snapshots()]
        if not nums:
            return [], "Nenhuma janela do MU encontrada agora."
        if slot is None:
            return nums, None
        if slot not in nums:
            return [], f"Não existe o slot {slot}. Slots agora: {', '.join(map(str, nums))}."
        return [slot], None

    def _status(self) -> str:
        snaps = self.engine.snapshots()
        if not snaps:
            return "Nenhuma janela do MU encontrada agora."
        now = self.clock()
        out = []
        for s in snaps:
            line = f'Slot {s.slot} "{s.name}" — {s.state.value} há {_ago(s.since, now)}'
            info = []
            if s.map:
                info.append(s.map + (f" {s.coords[0]},{s.coords[1]}" if s.coords else ""))
            if s.hp:
                info.append(f"HP {s.hp[0]}/{s.hp[1]}")
            if s.exp_per_h:
                pct = f" ({s.exp_pct_per_h:.1f}%/h)".replace(".", ",") if s.exp_pct_per_h else ""
                info.append(f"EXP/h {P.fmt_big(s.exp_per_h)}{pct}")
            if info:
                line += "\n   " + " · ".join(info)
            opened = [P.LABEL[k].split(" (")[0] for k in self.engine.panels.open_panels(s.slot)]
            if opened:
                line += "\n   Painéis abertos: " + ", ".join(opened)
            if self.engine.cfg.is_shop(s.slot):
                line += "\n   (loja)"
            out.append(line)
        if getattr(self.engine.alerts, "paused", False):
            out.append("⏸ Alertas pausados.")
        return "\n\n".join(out)

    def _prints(self, slot: int | None) -> list[Reply]:
        nums, err = self._targets(slot)
        if err:
            return [Reply(err)]
        out = []
        for n in nums:
            img = self.engine.frame_copy(n)
            if img is None:
                out.append(Reply(f"{self._header(n)}: sem imagem agora (janela minimizada ou fechada)."))
            else:
                out.append(Reply(f"{self._header(n)} — {time.strftime('%H:%M:%S')}", jpeg(img, 80)))
        return out

    def _panel(self, kind: str, slot: int | None) -> list[Reply]:
        if kind == "loja" and slot is None:
            shops = [s.slot for s in self.engine.snapshots() if self.engine.cfg.is_shop(s.slot)]
            if not shops:
                return [Reply("Nenhuma janela se chama Loja. No MU Sentinel, dê o nome \"Loja\" ao slot do "
                              "personagem que vende (Configurações → Slots).")]
            nums, err = shops, None
        else:
            nums, err = self._targets(slot)
        if err:
            return [Reply(err)]
        out, missing = [], []
        for n in nums:
            img = self.engine.frame_copy(n)
            if img is None:
                missing.append(f"{self._header(n)}: sem imagem agora (janela minimizada ou fechada)")
                continue
            r = self.engine.panels.report(n, img, kind)
            if r is None:
                missing.append(f"{self._header(n)}: {P.LABEL[kind]} não está aberto")
                continue
            title = P.LABEL[kind].split(" (")[0]
            name = r.data.get("nome")
            head = f"{self._header(n)} — {title}" + (f" · {name}" if name and kind == "personagem" else "")
            out.append(Reply(f"{head}\n{r.summary()}", jpeg(r.image)))
        if missing and (slot is not None or not out):
            out.append(Reply("\n".join(missing) + f"\n\nPara eu ver: {P.HOW_TO_OPEN[kind]}."))
        return out
