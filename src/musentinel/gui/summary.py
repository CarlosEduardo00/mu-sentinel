"""Resumo do estado em uma frase, para a barra de cima, o ícone da bandeja e a dica dele. Sem Qt."""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..core.state_machine import CRITICAL, State

ATTENTION = {State.PARADO, State.ILEGIVEL}


def display_name(slot: int, name: str) -> str:
    """Nome que aparece na tela: o que o usuário deu, ou "Janela N" se ainda for o nome padrão."""
    return f"Janela {slot}" if not name or name == f"Slot {slot}" else name


@dataclass
class Summary:
    status: str | None  # "ok", "atencao", "critico", "pausado" ou None (nenhuma janela)
    text: str


def summarize(snaps, paused: bool = False, paused_until: float | None = None) -> Summary:
    crit = [s for s in snaps if s.state in CRITICAL]
    if crit:
        n = len(crit)
        names = ", ".join(f"{display_name(s.slot, s.name)} {s.state.value}" for s in crit)
        text = f"{n} alerta{'s' if n > 1 else ''}: {names}"
        return Summary("critico", text + (" · alertas pausados" if paused else ""))
    if paused:
        until = ""
        if paused_until and paused_until != float("inf"):
            until = f" até {time.strftime('%H:%M', time.localtime(paused_until))}"
        return Summary("pausado", f"Alertas pausados{until}")
    if not snaps:
        return Summary(None, "Procurando o MU Online…")
    warn = [s for s in snaps if s.state in ATTENTION]
    if warn:
        names = ", ".join(f"{display_name(s.slot, s.name)} {s.state.value}" for s in warn)
        return Summary("atencao", f"Atenção: {names}")
    n = len(snaps)
    return Summary("ok", f"Tudo certo · {n} {'janela' if n == 1 else 'janelas'}")
