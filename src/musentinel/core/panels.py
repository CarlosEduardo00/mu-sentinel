"""Acompanha os painéis que o usuário deixa abertos no jogo, slot a slot.

- Checagem periódica (thread própria, para não atrasar o monitor): confere sem OCR se cada painel
  continua no lugar; se sumiu ou de tempos em tempos, procura de novo na tela inteira.
- Painel que estava aberto e fechou sem o usuário mexer no PC (relog, morte, teleporte) → aviso.
- Slot "Loja": lê o contador do Gremory Case (aba Personal Shop); subiu → aviso de venda.
- Pedido do usuário (/inventario, /personagem...): recorte do painel + o que deu para ler.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from .perception import panels as P
from .perception.ocr import OcrEngine

log = logging.getLogger(__name__)

RESCAN_S = 300  # procura painéis novos na tela inteira a cada 5 min
RECHECK_CLOSED_S = 90  # painel que fechou (já avisado): procura de novo a cada 1,5 min
SEEN_CHECKS = 2  # painel aberto em 2 checagens seguidas = "o usuário deixou aberto"
MISSING_CHECKS = 3  # sumido em 3 checagens seguidas = fechou
SHOP_CONFIRM = 2  # contador do Gremory lido igual 2 vezes antes de avisar a venda


@dataclass
class PanelEvent:
    kind: str  # "fechou" | "reabriu" | "venda" | "aba"
    panel: str
    detail: str = ""
    image: bytes | None = field(default=None, repr=False)


@dataclass
class _SlotState:
    hits: dict[str, P.PanelHit] = field(default_factory=dict)
    last_scan: float = 0.0
    open_n: dict[str, int] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)
    missing: dict[str, int] = field(default_factory=dict)
    warned: set[str] = field(default_factory=set)
    shop_base: int | None = None
    shop_pending: tuple[int, int] | None = None  # (contagem nova, vezes lida)
    shop_tab_warned: bool = False
    last_grid: list[list[bool]] | None = None


def jpeg(img: np.ndarray, quality: int = 85) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else None


class PanelService:
    def __init__(self, ocr: OcrEngine | None = None, clock: Callable[[], float] = time.time) -> None:
        self._ocr = ocr
        self._clock = clock
        self._lock = threading.RLock()  # um OCR por vez; leituras de slots diferentes não se misturam
        self._slots: dict[int, _SlotState] = {}

    @property
    def ocr(self) -> OcrEngine:
        if self._ocr is None:
            self._ocr = OcrEngine()  # instância própria: não disputa com a leitura do HUD
        return self._ocr

    def _st(self, slot: int) -> _SlotState:
        return self._slots.setdefault(slot, _SlotState())

    def forget(self, slot: int) -> None:
        with self._lock:
            self._slots.pop(slot, None)

    def open_panels(self, slot: int) -> list[str]:
        """Painéis vistos abertos na última checagem, na ordem de P.KINDS."""
        with self._lock:
            st = self._slots.get(slot)
            return [k for k in P.KINDS if st and k in st.hits]

    # ------------------------------------------------------------------ localizar
    def _refresh_hits(self, st: _SlotState, img: np.ndarray, force: bool = False,
                      every_s: float = RESCAN_S) -> list | None:
        """Confere os painéis conhecidos (sem OCR); procura na tela toda se algum saiu do lugar, se `force`
        ou a cada `every_s`. Devolve as caixas da varredura (None se não varreu)."""
        now = self._clock()
        gone = [k for k, h in st.hits.items() if not P.still_open(img, h)]
        if not force and not gone and now - st.last_scan < every_s:
            return None
        hits, boxes = P.scan(img, self.ocr)
        st.hits = hits
        st.last_scan = now
        log.debug("painéis encontrados: %s", sorted(hits))
        return boxes

    # ------------------------------------------------------------------ checagem periódica
    def check(self, slot: int, img: np.ndarray, *, live: bool, user_active: bool,
              is_shop: bool) -> list[PanelEvent]:
        with self._lock:
            st = self._st(slot)
            if not live:  # morto/desconectado/travado: o alerta crítico já cobre; não conta painel sumido
                st.missing.clear()
                st.shop_pending = None
                return []
            expected = set(st.seen) | ({"loja"} if is_shop else set())
            absent = expected - set(st.hits)
            if absent - st.warned:
                self._refresh_hits(st, img, force=True)  # confirmando se fechou mesmo
            elif absent:
                self._refresh_hits(st, img, every_s=RECHECK_CLOSED_S)  # já avisou: espera reabrir
            else:
                self._refresh_hits(st, img)
            events: list[PanelEvent] = []
            for k in P.KINDS:
                if k in st.hits:
                    st.open_n[k] = st.open_n.get(k, 0) + 1
                    st.missing[k] = 0
                    if st.open_n[k] >= SEEN_CHECKS:
                        st.seen.add(k)
                    if k in st.warned:
                        st.warned.discard(k)
                        events.append(PanelEvent("reabriu", k, f"{P.LABEL[k]} aberto de novo"))
                    continue
                st.open_n[k] = 0
                if k not in expected:
                    continue
                if user_active:  # usuário mexendo no PC: fechou de propósito (a loja continua esperada)
                    if not (is_shop and k == "loja"):
                        st.seen.discard(k)
                    st.missing[k] = 0
                    continue
                st.missing[k] = st.missing.get(k, 0) + 1
                if st.missing[k] >= MISSING_CHECKS and k not in st.warned:
                    st.warned.add(k)
                    what = "não está aberto" if k not in st.seen else "fechou"
                    events.append(PanelEvent("fechou", k, f"{P.LABEL[k]} {what}: {P.HOW_TO_OPEN[k]} para eu "
                                                          "continuar acompanhando"))
            if is_shop and "loja" in st.hits:
                events += self._check_shop(st, img)
            return events

    def _check_shop(self, st: _SlotState, img: np.ndarray) -> list[PanelEvent]:
        hit = st.hits["loja"]
        tab = P.shop_selected_tab(img, hit)
        if tab is not None and tab != P.SHOP_PERSONAL_TAB:
            st.shop_pending = None
            if not st.shop_tab_warned:
                st.shop_tab_warned = True
                return [PanelEvent("aba", "loja", "o Gremory Case está aberto em outra aba: selecione "
                                                  "Personal Shop para eu ver as vendas")]
            return []
        st.shop_tab_warned = False
        counter = P.read_shop_counter(img, hit, self.ocr)
        if counter is None:  # algo por cima do contador (dica de item, menu): tenta na próxima
            return []
        count, cap = counter
        if st.shop_base is None or count < st.shop_base:
            st.shop_base = count  # primeira leitura, ou o usuário retirou itens
            st.shop_pending = None
            return []
        if count == st.shop_base:
            st.shop_pending = None
            return []
        n = st.shop_pending[1] + 1 if st.shop_pending and st.shop_pending[0] == count else 1
        st.shop_pending = (count, n)
        if n < SHOP_CONFIRM:
            return []
        old, st.shop_base, st.shop_pending = st.shop_base, count, None
        diff = count - old
        detail = (f"Gremory Case (Personal Shop): {old} → {count} de {cap} "
                  f"({'+1 item' if diff == 1 else f'+{diff} itens'}). Confira o que foi vendido.")
        return [PanelEvent("venda", "loja", detail, jpeg(P.crop(img, hit)))]

    # ------------------------------------------------------------------ pedido do usuário
    def report(self, slot: int, img: np.ndarray, kind: str) -> P.PanelReading | None:
        """Lê um painel agora. None = o painel não está aberto na tela."""
        with self._lock:
            st = self._st(slot)
            hit = st.hits.get(kind)
            boxes = None
            if hit is None or not P.still_open(img, hit):
                boxes = self._refresh_hits(st, img, force=True)
                hit = st.hits.get(kind)
            if hit is None:
                return None
            reading = P.read(kind, img, hit, self.ocr, boxes)
            if kind == "inventario" and "grid" in reading.data:
                grid = reading.data["grid"]
                if st.last_grid is not None and len(st.last_grid) == len(grid):
                    new = sum(1 for r0, r1 in zip(st.last_grid, grid) for a, b in zip(r0, r1) if b and not a)
                    freed = sum(1 for r0, r1 in zip(st.last_grid, grid) for a, b in zip(r0, r1) if a and not b)
                    reading.data.update(new=new, freed=freed)
                    reading.fields["Desde o último pedido"] = f"+{new} ocupados · {freed} liberados"
                st.last_grid = grid
            return reading
