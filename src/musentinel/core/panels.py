"""Acompanha os painéis que o usuário deixa abertos no jogo, slot a slot.

- Checagem periódica (thread própria, para não atrasar o monitor): confere sem OCR se cada painel
  continua no lugar; se sumiu ou de tempos em tempos, procura de novo na tela inteira.
- Painel que estava aberto e fechou sem o usuário mexer no PC (relog, morte, teleporte) → aviso.
- Slot "Loja": lê o contador do Gremory Case (aba Personal Shop); subiu → aviso de venda.
- Pedido do usuário (/inventario, /personagem...): recorte do painel + o que deu para ler.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .perception import panels as P
from .perception.ocr import OcrEngine

log = logging.getLogger(__name__)

RESCAN_S = 600  # procura painéis novos na tela inteira a cada 10 min (OCR da tela toda é caro)
RECHECK_CLOSED_S = 90  # painel que fechou (já avisado): procura de novo a cada 1,5 min
SEEN_CHECKS = 2  # painel aberto em 2 checagens seguidas = "o usuário deixou aberto"
MISSING_CHECKS = 3  # sumido em 3 checagens seguidas = fechou
SHOP_CONFIRM = 2  # contador do Gremory lido igual 2 vezes antes de avisar a venda
OCR_THREADS = 2  # medido: 2 núcleos ~3,0 s por tela; todos os 16 ~4,0 s (disputa entre threads); 1 ~5,1 s


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
    shop_band: np.ndarray | None = field(default=None, repr=False)  # imagem do contador na última leitura
    last_grid: list[list[bool]] | None = None


def jpeg(img: np.ndarray, quality: int = 85) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else None


class PanelService:
    def __init__(self, ocr: OcrEngine | None = None, clock: Callable[[], float] = time.time,
                 store: Path | None = None) -> None:
        self._ocr = ocr
        self._clock = clock
        self._store = store  # última contagem do Gremory Case por janela (aviso de venda com o app fechado)
        self._counts: dict[str, int] = self._load_counts()
        self._shop_pub: dict[int, tuple[int, int, float | None]] = {}
        self._lock = threading.RLock()  # um OCR por vez; leituras de slots diferentes não se misturam
        self._slots: dict[int, _SlotState] = {}
        # painéis abertos por slot, para o monitor consultar sem esperar uma varredura (que leva segundos)
        self._open: dict[int, list[str]] = {}
        self._hits_pub: dict[int, dict[str, P.PanelHit]] = {}

    @property
    def ocr(self) -> OcrEngine:
        if self._ocr is None:
            # instância própria e só 2 núcleos: a leitura da tela inteira (~3 s) não atrasa o monitor
            self._ocr = OcrEngine(threads=OCR_THREADS)
        return self._ocr

    def _st(self, slot: int) -> _SlotState:
        return self._slots.setdefault(slot, _SlotState())

    def forget(self, slot: int) -> None:
        with self._lock:
            self._slots.pop(slot, None)
            self._open.pop(slot, None)
            self._hits_pub.pop(slot, None)
            self._shop_pub.pop(slot, None)

    def open_panels(self, slot: int) -> list[str]:
        """Painéis vistos abertos na última checagem, na ordem de P.KINDS. Não espera o OCR."""
        return list(self._open.get(slot, []))

    def hit(self, slot: int, kind: str) -> P.PanelHit | None:
        """Onde o painel estava na última checagem (sem esperar o OCR)."""
        return self._hits_pub.get(slot, {}).get(kind)

    def _publish(self, slot: int, st: _SlotState) -> None:
        self._open[slot] = [k for k in P.KINDS if k in st.hits]
        self._hits_pub[slot] = dict(st.hits)

    def adopt(self, slot: int, hits: dict[str, P.PanelHit]) -> None:
        """Usa uma varredura feita por outra rotina (ex.: calibração) como a mais recente."""
        with self._lock:
            st = self._st(slot)
            st.hits = dict(hits)
            st.last_scan = self._clock()
            self._publish(slot, st)

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
              is_shop: bool, shop_key: str | None = None) -> list[PanelEvent]:
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
            if "loja" in st.hits:  # vendas: em qualquer janela com o Gremory Case aberto (não só na "Loja")
                events += self._check_shop(st, img, slot, is_shop, shop_key or f"slot {slot}")
            self._publish(slot, st)
            return events

    # ------------------------------------------------------------------ Gremory Case (vendas)
    def shop_status(self, slot: int) -> tuple[int, int, float | None] | None:
        """(itens, capacidade, hora da última venda) do Gremory Case desta janela, se já foi lido."""
        return self._shop_pub.get(slot)

    def _load_counts(self) -> dict[str, int]:
        try:
            if self._store and self._store.exists():
                return {str(k): int(v) for k, v in json.loads(self._store.read_text(encoding="utf-8")).items()}
        except Exception:
            log.warning("não consegui ler %s", self._store)
        return {}

    def _save_count(self, key: str, count: int) -> None:
        if not self._store or self._counts.get(key) == count:
            return
        self._counts[key] = count
        try:
            self._store.write_text(json.dumps(self._counts, ensure_ascii=False), encoding="utf-8")
        except OSError:
            log.warning("não consegui salvar a contagem do Gremory Case")

    def _check_shop(self, st: _SlotState, img: np.ndarray, slot: int, is_shop: bool,
                    key: str) -> list[PanelEvent]:
        hit = st.hits["loja"]
        tab = P.shop_selected_tab(img, hit)
        if tab is not None and tab != P.SHOP_PERSONAL_TAB:
            st.shop_pending = None
            if is_shop and not st.shop_tab_warned:  # personagem de caça olhando outra aba: não é problema
                st.shop_tab_warned = True
                return [PanelEvent("aba", "loja", "o Gremory Case está aberto em outra aba: selecione "
                                                  "Personal Shop para eu ver as vendas")]
            return []
        st.shop_tab_warned = False
        band = P.shop_counter_crop(img, hit)
        if band is not None and st.shop_base is not None and st.shop_pending is None \
                and P.same_image(band, st.shop_band):
            return []  # contador com a mesma imagem da última leitura: nada mudou, sem OCR
        counter = P.read_shop_counter(img, hit, self.ocr)
        if counter is not None and band is not None:
            st.shop_band = band.copy()
        if counter is None:  # algo por cima do contador (dica de item, menu): tenta na próxima
            return []
        count, cap = counter
        last_sale = (self._shop_pub.get(slot) or (0, 0, None))[2]
        self._shop_pub[slot] = (count, cap, last_sale)
        if st.shop_base is None:
            st.shop_base, st.shop_pending = count, None
            before = self._counts.get(key)
            self._save_count(key, count)
            if before is not None and count > before:  # vendeu com o MU Sentinel fechado
                return [self._sale(slot, before, count, cap, img, hit, " enquanto o MU Sentinel estava fechado")]
            return []
        if count < st.shop_base:  # o usuário retirou itens: nova base, sem aviso
            st.shop_base, st.shop_pending = count, None
            self._save_count(key, count)
            return []
        if count == st.shop_base:
            st.shop_pending = None
            return []
        n = st.shop_pending[1] + 1 if st.shop_pending and st.shop_pending[0] == count else 1
        st.shop_pending = (count, n)
        if n < SHOP_CONFIRM:
            return []
        old, st.shop_base, st.shop_pending = st.shop_base, count, None
        self._save_count(key, count)
        return [self._sale(slot, old, count, cap, img, hit)]

    def _sale(self, slot: int, old: int, count: int, cap: int, img: np.ndarray, hit: P.PanelHit,
              when: str = "") -> PanelEvent:
        self._shop_pub[slot] = (count, cap, self._clock())
        diff = count - old
        detail = (f"item novo no Gremory Case (Personal Shop){when}: {old} → {count} de {cap} "
                  f"({'+1 item' if diff == 1 else f'+{diff} itens'}). Confira o que foi vendido.")
        return PanelEvent("venda", "loja", detail, jpeg(P.crop(img, hit)))

    # ------------------------------------------------------------------ pedido do usuário
    def report(self, slot: int, img: np.ndarray, kind: str) -> P.PanelReading | None:
        """Lê um painel agora. None = o painel não está aberto na tela."""
        with self._lock:
            st = self._st(slot)
            hit = st.hits.get(kind)
            boxes = None
            if hit is None or not P.still_open(img, hit):
                boxes = self._refresh_hits(st, img, force=True)
                self._publish(slot, st)
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
