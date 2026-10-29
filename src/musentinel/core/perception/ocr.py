"""OCR (RapidOCR/ONNX) para texto livre: nome do mapa e mensagens do sistema."""

from __future__ import annotations

import difflib
import threading
from collections import OrderedDict

import cv2
import numpy as np

# Mapas do MU Online (client em inglês). Editável na configuração.
DEFAULT_MAPS = [
    "Lorencia", "Dungeon", "Devias", "Noria", "Lost Tower", "Atlans", "Tarkan", "Icarus",
    "Elbeland", "Aida", "Crywolf Fortress", "Kanturu", "Kanturu Relics", "Kanturu Ruins",
    "Raklion", "Swamp of Calmness", "Vulcanus", "Karutan", "Acheron", "Debenter",
    "Uruk Mountain", "Nars", "Ferea", "Nixies Lake", "Labyrinth of Dimensions", "Deep Dungeon",
    "Swamp of Darkness", "Kubera Mine", "Abyss Atlans", "Scorched Canyon", "Red Smoke Icarus",
    "Ashen Aida", "Arnil", "Old Kethotum", "Burning Kethotum", "Kanturu Undergrounds",
    "Ignis Volcano", "Bloody Tarkan", "Tormented Square", "Nightmare Kanturu",
    "Crimson Icarus", "Temple of Arnil", "Gray Aida", "Kardamahal", "Blaze Kethotum",
    "Silent Map", "Loren Market", "Barracks of Balgass", "Refuge of Balgass", "Land of Trials",
    "Stadium",
]

DEFAULT_CITIES = ["Lorencia", "Devias", "Noria", "Elbeland"]


SMALL_H = 20  # recortes até esta altura (px) têm texto pequeno


class OcrEngine:
    """Carrega o modelo só quando for usado e guarda cache por imagem."""

    def __init__(self, cache_size: int = 256):
        self._engine = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[bytes, tuple[str, float]] = OrderedDict()
        self._cache_size = cache_size

    def _get(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def read_line(self, img_bgr: np.ndarray) -> tuple[str, float]:
        """Uma linha de texto (sem detecção). Retorna (texto, confiança)."""
        key = _key(img_bgr)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
            from .glyphs import ink

            # texto escuro em fundo claro, ampliado: o reconhecedor erra menos letras
            inv = 255 - ink(img_bgr)
            if img_bgr.shape[0] <= SMALL_H:
                # texto pequeno (janela 800x600): amplia mais e dá margem
                big = cv2.resize(inv, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
                big = cv2.copyMakeBorder(big, 8, 8, 16, 16, cv2.BORDER_CONSTANT, value=int(np.median(inv)))
            else:
                big = cv2.resize(inv, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            big = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
            res, _ = self._get()(big, use_det=False, use_cls=False, use_rec=True)
            text, score = ("", 0.0)
            if res:
                text, score = str(res[0][0]).strip(), float(res[0][1])
            self._remember(key, (text, score))
            return text, score

    def read_number(self, img_bgr: np.ndarray, charset: str) -> tuple[str | None, float]:
        """Lê um campo numérico em duas escalas; só aceita se as duas concordarem.

        Serve de segundo leitor, independente do template matching, para
        rotular prints automaticamente.
        """
        from .glyphs import ink

        im = ink(img_bgr)
        if "/" in charset:
            # "61212 / 1852300": a barra entre espaços às vezes vira '7' no OCR.
            # Lê cada número separado e junta com '/'.
            words = _words(im)
            if len(words) == 3 and words[1][1] - words[1][0] <= 6:
                digits = charset.replace("/", "")
                (a0, a1), _, (b0, b1) = words
                left, s1 = self.read_number(img_bgr[:, max(0, a0 - 2) : a1 + 2], digits)
                right, s2 = self.read_number(img_bgr[:, max(0, b0 - 2) : b1 + 2], digits)
                if left and right:
                    return f"{left}/{right}", min(s1, s2)
                return None, 0.0

        inv = 255 - im
        bg = int(np.median(inv))
        reads = []
        with self._lock:
            for sc in ((3, 4) if img_bgr.shape[0] <= SMALL_H else (2, 3)):
                b = cv2.resize(inv, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
                b = cv2.copyMakeBorder(b, 8, 8, 16, 16, cv2.BORDER_CONSTANT, value=bg)
                res, _ = self._get()(cv2.cvtColor(b, cv2.COLOR_GRAY2BGR), use_det=False, use_cls=False, use_rec=True)
                if not res:
                    return None, 0.0
                raw = str(res[0][0])
                if "," in charset and "." not in charset:
                    raw = raw.replace(".", ",")  # vírgula pequena costuma sair como ponto
                text = "".join(c for c in raw if c in charset)
                reads.append((text, float(res[0][1])))
        (t1, s1), (t2, s2) = reads
        if not t1 or t1 != t2:
            return None, 0.0
        return t1, min(s1, s2)

    def read_block(self, img_bgr: np.ndarray) -> list[tuple[str, float]]:
        """Várias linhas (com detecção), de cima para baixo."""
        with self._lock:
            res, _ = self._get()(img_bgr)
        if not res:
            return []
        res = sorted(res, key=lambda r: min(p[1] for p in r[0]))
        return [(str(r[1]).strip(), float(r[2])) for r in res]

    def _remember(self, key: bytes, val: tuple[str, float]) -> None:
        self._cache[key] = val
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _words(im: np.ndarray, min_gap: int = 3) -> list[tuple[int, int]]:
    """Trechos de texto separados por espaços (>= min_gap colunas sem tinta)."""
    thr = max(50.0, 0.3 * float(im.max()))
    cols = (im >= thr).any(axis=0)
    words: list[list[int]] = []
    gap = min_gap
    for x, on in enumerate(cols):
        if on:
            if gap >= min_gap:
                words.append([x, x + 1])
            else:
                words[-1][1] = x + 1
            gap = 0
        else:
            gap += 1
    return [(a, b) for a, b in words]


def _key(img: np.ndarray) -> bytes:
    """Chave de cache tolerante a ruído leve: imagem reduzida e quantizada."""
    small = cv2.resize(img.min(axis=2) if img.ndim == 3 else img, (32, 8), interpolation=cv2.INTER_AREA)
    return (small // 32).astype(np.uint8).tobytes()


def match_name(text: str, names: list[str], cutoff: float = 0.75) -> tuple[str | None, float]:
    """Casa o texto lido com a lista de nomes conhecidos (tolerante a erro de OCR)."""
    if not text:
        return None, 0.0
    norm = {n.lower().replace(" ", ""): n for n in names}
    t = text.lower().replace(" ", "")
    if t in norm:
        return norm[t], 1.0
    best = difflib.get_close_matches(t, norm.keys(), n=1, cutoff=cutoff)
    if not best:
        return None, 0.0
    ratio = difflib.SequenceMatcher(None, t, best[0]).ratio()
    return norm[best[0]], ratio
