"""Descoberta das janelas do client e associação PID/HWND → slot.

Slots são numerados a partir de 1. Quando um client é reaberto, a janela nova
herda o slot da que sumiu com posição/tamanho mais parecidos. Se dois slots vagos
empatarem, fica com o menor número e o evento avisa que a associação foi ambígua.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths, winapi

log = logging.getLogger(__name__)
NEAR_PX = 60  # janela reaberta "no mesmo lugar" (tolerância)


@dataclass
class SlotBinding:
    slot: int
    hwnd: int
    pid: int
    rect: tuple[int, int, int, int]  # left, top, width, height
    info: winapi.WindowInfo | None = None


def _rect_of(w: winapi.WindowInfo) -> tuple[int, int, int, int]:
    try:
        r = winapi.frame_bounds(w.hwnd)
        return (r.left, r.top, r.width, r.height)
    except Exception:
        return (0, 0, *w.client_size)


def _distance(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + 0.5 * (abs(a[2] - b[2]) + abs(a[3] - b[3]))


class Discovery:
    def __init__(
        self,
        title: str = "MU",
        process: str | None = "main.exe",
        lister: Callable[[], list[winapi.WindowInfo]] | None = None,
        rect_of: Callable[[winapi.WindowInfo], tuple[int, int, int, int]] = _rect_of,
        store: Path | None = None,
    ) -> None:
        self.title = title
        self.process = process
        self._lister = lister or (lambda: winapi.list_windows(self.title, self.process))
        self._rect_of = rect_of
        self.store = store
        self.active: dict[int, SlotBinding] = {}  # slot → janela atual
        self.vacant: dict[int, SlotBinding] = {}  # slot → última janela que sumiu
        self.events: list[str] = []
        self._load()

    # ------------------------------------------------------------------
    def refresh(self) -> dict[int, SlotBinding]:
        """Atualiza e retorna slot → janela. Mensagens novas ficam em self.events."""
        self.events = []
        try:
            wins = self._lister()
        except Exception:
            log.exception("falha ao listar janelas")
            return dict(self.active)
        by_hwnd = {w.hwnd: w for w in wins}

        for slot, b in list(self.active.items()):
            w = by_hwnd.pop(b.hwnd, None)
            if w is None or w.pid != b.pid:
                self.vacant[slot] = self.active.pop(slot)
                if w is not None:
                    by_hwnd[w.hwnd] = w  # mesmo hwnd, outro processo: trata como janela nova
                continue
            b.info = w
            if not w.minimized:
                b.rect = self._rect_of(w)

        new = sorted(by_hwnd.values(), key=lambda w: (self._rect_of(w)[0], self._rect_of(w)[1], w.pid))
        rects = {w.hwnd: self._rect_of(w) for w in new}
        # 1ª passada: janela reaberta no mesmo lugar herda o slot (o par mais próximo primeiro)
        pairs = sorted(
            ((_distance(vb.rect, rects[w.hwnd]), slot, w) for w in new for slot, vb in self.vacant.items()
             if _distance(vb.rect, rects[w.hwnd]) <= NEAR_PX),
            key=lambda t: (t[0], t[1]),
        )
        taken_w: set[int] = set()
        for d, slot, w in pairs:
            if w.hwnd in taken_w or slot not in self.vacant:
                continue
            others = [s2 for d2, s2, w2 in pairs if w2.hwnd == w.hwnd and s2 != slot and s2 in self.vacant
                      and d2 - d < 10]
            if others:
                self.events.append(
                    f"associação ambígua: janela nova pode ser o slot {slot} ou {others[0]}; usei o {slot}."
                )
            self._bind(slot, w, rects[w.hwnd])
            taken_w.add(w.hwnd)
        # 2ª passada: as demais pegam o menor número livre. Slots lembrados de outra execução
        # (sem janela nesta sessão) não ficam reservados; os que fecharam nesta sessão ficam.
        for w in new:
            if w.hwnd in taken_w:
                continue
            reserved = set(self.active) | {s for s, vb in self.vacant.items() if vb.hwnd}
            n = 1
            while n in reserved:
                n += 1
            if n > 8 and self.vacant:
                n = min(self.vacant)  # não cria slots infinitos
            self._bind(n, w, rects[w.hwnd])
        self._save()
        return dict(self.active)

    def _bind(self, slot: int, w: winapi.WindowInfo, rect) -> None:
        self.vacant.pop(slot, None)
        self.active[slot] = SlotBinding(slot, w.hwnd, w.pid, rect, w)

    def known_slots(self) -> list[int]:
        return sorted(set(self.active) | set(self.vacant))

    def forget(self, slot: int) -> None:
        self.vacant.pop(slot, None)
        self._save()

    def swap(self, a: int, b: int) -> None:
        for d in (self.active, self.vacant):
            ba, bb = d.pop(a, None), d.pop(b, None)
            if ba:
                ba.slot = b
                d[b] = ba
            if bb:
                bb.slot = a
                d[a] = bb
        self._save()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.store or not self.store.exists():
            return
        try:
            data = json.loads(self.store.read_text(encoding="utf-8"))
            for k, r in data.get("rects", {}).items():
                self.vacant[int(k)] = SlotBinding(int(k), 0, 0, tuple(r))
        except Exception:
            log.warning("slots.json ilegível; começando do zero")

    def _save(self) -> None:
        if not self.store:
            return
        rects = {str(s): list(b.rect) for s, b in {**self.vacant, **self.active}.items()}
        try:
            self.store.write_text(json.dumps({"rects": rects}), encoding="utf-8")
        except OSError:
            pass


def default_store() -> Path:
    return paths.data_dir() / "slots.json"
