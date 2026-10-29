"""Leitura de texto curto do HUD (dígitos, '/', ',', ':') por template matching.

O HUD usa texto claro sobre fundos variados (orbe vermelho, barra verde, painel
semitransparente). Trabalhamos sobre o "canal mínimo" (min de B,G,R): texto
branco/cinza fica alto, fundos saturados ficam baixos.

Os modelos de cada caractere são aprendidos de exemplos rotulados (calibração),
não desenhados à mão: assim servem para qualquer resolução/escala do Windows.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

import cv2
import numpy as np

MATCH_MIN = 0.82  # pontuação mínima para aceitar um caractere candidato
INK_RATIO = 0.7  # a janela precisa ter pelo menos 70% do brilho máximo do modelo
LINE_TOL = 2  # px de tolerância vertical em relação à linha de texto


def ink(img_bgr: np.ndarray) -> np.ndarray:
    """Imagem de 'tinta' em uint8: claro E pouco saturado (texto branco/cinza).

    min(B,G,R) já derruba fundos vermelhos/azuis; a penalidade de saturação
    derruba realces claros coloridos (barra verde do EXP, lava).
    """
    if img_bgr.ndim == 2:
        return img_bgr
    a = img_bgr.astype(np.int16)
    mn = a.min(axis=2)
    sat = a.max(axis=2) - mn
    return np.clip(mn - sat // 2, 0, 255).astype(np.uint8)


@dataclass
class Glyph:
    char: str
    image: np.ndarray  # uint8, canal mínimo

    def to_b64(self) -> str:
        ok, png = cv2.imencode(".png", self.image)
        assert ok
        return base64.b64encode(png.tobytes()).decode()

    @staticmethod
    def from_b64(char: str, data: str) -> Glyph:
        arr = np.frombuffer(base64.b64decode(data), np.uint8)
        return Glyph(char, cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE))


@dataclass
class GlyphFont:
    """Conjunto de modelos por caractere (várias variantes por caractere)."""

    glyphs: dict[str, list[Glyph]] = field(default_factory=dict)
    max_variants: int = 6

    def chars(self) -> set[str]:
        return {c for c, v in self.glyphs.items() if v}

    def add(self, g: Glyph) -> None:
        variants = self.glyphs.setdefault(g.char, [])
        for v in variants:
            if v.image.shape == g.image.shape and _ncc(v.image, g.image) > 0.97:
                return  # já temos uma variante praticamente igual
        variants.append(g)
        if len(variants) > self.max_variants:
            variants.pop(0)

    def to_dict(self) -> dict[str, list[str]]:
        return {c: [g.to_b64() for g in v] for c, v in self.glyphs.items()}

    @staticmethod
    def from_dict(d: dict[str, list[str]]) -> GlyphFont:
        f = GlyphFont()
        for c, items in d.items():
            f.glyphs[c] = [Glyph.from_b64(c, s) for s in items]
        return f


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float32).ravel()
    b = b.astype(np.float32).ravel()
    a -= a.mean()
    b -= b.mean()
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / d) if d > 0 else 0.0


# ---------------------------------------------------------------- aprendizado


def _segments(cols: np.ndarray) -> list[tuple[int, int]]:
    segs, start = [], None
    for i, on in enumerate(cols):
        if on and start is None:
            start = i
        elif not on and start is not None:
            segs.append((start, i))
            start = None
    if start is not None:
        segs.append((start, len(cols)))
    return segs


# largura relativa típica de cada caractere (1.0 = dígito): (mínima, máxima)
_WIDTH = {",": (0.2, 0.8), ":": (0.2, 0.8), ".": (0.2, 0.8), "/": (0.35, 1.3)}
_DIGIT_W = (0.55, 1.45)


def text_extent(im: np.ndarray) -> tuple[int, int, int, int] | None:
    """Caixa (x0, y0, x1, y1) do texto claro na ROI."""
    thr = max(100.0, 0.6 * float(im.max()))
    mask = im >= thr
    cols = np.where(mask.sum(axis=0) >= 1)[0]
    rows = np.where(mask.sum(axis=1) >= 2)[0]
    if cols.size == 0 or rows.size == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _widen(mask: np.ndarray, x0: int, x1: int) -> tuple[int, int]:
    """Estende [x0, x1) enquanto as colunas vizinhas ainda têm tinta fraca."""
    cols = mask.any(axis=0)
    while x0 > 0 and cols[x0 - 1]:
        x0 -= 1
    while x1 < len(cols) and cols[x1]:
        x1 += 1
    return x0, x1


def split_glyphs(roi_bgr: np.ndarray, label: str) -> list[np.ndarray] | None:
    """Divide o texto da ROI em len(label) recortes (rótulo sem espaços).

    Os dígitos do HUD encostam uns nos outros, então não dá para separar por
    coluna vazia. Usamos programação dinâmica: escolhe os cortes com menos
    tinta, respeitando a largura plausível de cada caractere do rótulo.
    """
    n = len(label)
    im = ink(roi_bgr)
    box = text_extent(im)
    if box is None or n == 0:
        return None
    x0, y0, x1, y1 = box
    thr = max(50.0, 0.3 * float(im.max()))  # baixo: a '/' é fina e fraca
    x0, x1 = _widen(im[y0:y1] >= thr, x0, x1)
    has_ink = (im[y0:y1, x0:x1] >= thr).any(axis=0)
    # espaços entre palavras ("7026 / 79300") viram 1 coluna só
    keep: list[int] = []
    run = 0
    for i, on in enumerate(has_ink):
        run = 0 if on else run + 1
        if run <= 1:
            keep.append(x0 + i)
    cols = np.array(keep)
    L = len(cols)
    rel = [_WIDTH.get(c, _DIGIT_W) for c in label]
    unit = L / sum((a + b) / 2 for a, b in rel)
    lo = [max(1, int(np.floor(a * unit))) for a, _ in rel]
    hi = [max(lo[i], int(np.ceil(b * unit))) for i, (_, b) in enumerate(rel)]

    # custo de cortar antes da coluna p = tinta naquela coluna (fundo descontado)
    region = im[y0:y1][:, cols].astype(np.float32)
    prof = np.clip(region - np.median(region), 0, None).sum(axis=0)
    prof = np.append(prof, 0.0)

    INF = float("inf")
    cost = np.full((n + 1, L + 1), INF)
    back = np.zeros((n + 1, L + 1), dtype=np.int32)
    cost[0, 0] = 0.0
    for i in range(n):
        for p in range(L + 1):
            if cost[i, p] == INF:
                continue
            for q in range(p + lo[i], min(L, p + hi[i]) + 1):
                c = cost[i, p] + (prof[q] if q < L else 0.0)
                if c < cost[i + 1, q]:
                    cost[i + 1, q] = c
                    back[i + 1, q] = p
    if cost[n, L] == INF:
        return None
    cuts = [L]
    for i in range(n, 0, -1):
        cuts.append(int(back[i, cuts[-1]]))
    cuts.reverse()

    ya, yb = max(0, y0 - 1), min(im.shape[0], y1 + 1)
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        piece = [c for c in cols[a:b] if (im[y0:y1, c] >= thr).any()]
        if not piece:
            return None
        ca, cb = piece[0], piece[-1] + 1  # recorte aparado nas colunas com tinta
        out.append(im[ya:yb, ca:cb].copy())
    return out


def learn(font: GlyphFont, roi_bgr: np.ndarray, label: str) -> bool:
    """Aprende os caracteres de um exemplo rotulado. Espaços no rótulo são ignorados."""
    chars = [c for c in label if not c.isspace()]
    if not chars:
        return False
    parts = split_glyphs(roi_bgr, "".join(chars))
    if parts is None:
        return False
    for c, img in zip(chars, parts):
        font.add(Glyph(c, img))
    return True


# ---------------------------------------------------------------- leitura


@dataclass(frozen=True)
class Hit:
    x: int
    w: int
    char: str
    score: float
    y: int = 0
    h: int = 0


def read_text(roi_bgr: np.ndarray, font: GlyphFont, charset: str | None = None) -> tuple[str, float]:
    """Lê o texto da ROI. Retorna (texto, confiança 0..1). Texto vazio = nada reconhecido."""
    im = ink(roi_bgr)
    if float(im.max()) - float(im.min()) < 30:  # sem contraste: não há texto
        return "", 0.0

    hits: list[Hit] = []
    for ch, variants in font.glyphs.items():
        if charset is not None and ch not in charset:
            continue
        for g in variants:
            th, tw = g.image.shape
            if th > im.shape[0] or tw > im.shape[1]:
                continue
            ink_min = INK_RATIO * float(g.image.max())
            res = cv2.matchTemplate(im, g.image, cv2.TM_CCOEFF_NORMED)
            res = np.nan_to_num(res, nan=0.0)
            col = res.max(axis=0)
            rowpos = res.argmax(axis=0)
            # máximos locais por coluna
            for x in range(col.shape[0]):
                s = float(col[x])
                if s < MATCH_MIN:
                    continue
                lo, hi = max(0, x - 1), min(col.shape[0], x + 2)
                if s < col[lo:hi].max():
                    continue
                y = int(rowpos[x])
                if float(im[y : y + th, x : x + tw].max()) < ink_min:
                    continue
                hits.append(Hit(x, tw, ch, s, y, th))

    # supressão de não-máximos: maior pontuação primeiro, sem sobreposição relevante
    # (caracteres mais largos ganham empate, para '1' não "caber" dentro do '4')
    hits.sort(key=lambda h: (h.score + 0.002 * h.w), reverse=True)
    chosen: list[Hit] = []
    for h in hits:
        ok = True
        for c in chosen:
            ov = min(h.x + h.w, c.x + c.w) - max(h.x, c.x)
            if ov > 0.35 * min(h.w, c.w):
                ok = False
                break
        if ok:
            chosen.append(h)
    if not chosen:
        return "", 0.0
    # todos os caracteres de uma leitura estão na mesma linha (modelos têm a altura da linha)
    strong = sorted(chosen, key=lambda h: h.score, reverse=True)[: max(1, len(chosen) // 2)]
    line_y = int(np.median([h.y for h in strong]))
    chosen = [h for h in chosen if abs(h.y - line_y) <= LINE_TOL]
    if not chosen:
        return "", 0.0
    chosen.sort(key=lambda h: h.x)
    text = "".join(h.char for h in chosen)
    conf = min(h.score for h in chosen)

    # Toda tinta da linha precisa estar explicada por algum caractere. Se sobrar
    # um trecho com tinta sem caractere (dígito desconhecido), a leitura não vale:
    # melhor "ilegível" do que um número com um dígito a menos.
    if _uncovered_ink(im, chosen, line_y) >= UNCOVERED_MAX:
        return text, min(conf, 0.3)
    return text, conf


UNCOVERED_MAX = 3  # colunas seguidas com tinta e sem caractere


def _uncovered_ink(im: np.ndarray, chosen: list[Hit], line_y: int) -> int:
    h = max(c.h for c in chosen)
    band = im[line_y : line_y + h]
    thr = max(100.0, 0.6 * float(band.max()))
    cols = (band >= thr).any(axis=0)
    covered = np.zeros_like(cols)
    for c in chosen:
        covered[max(0, c.x - 1) : c.x + c.w + 1] = True
    run = best = 0
    for on, cov in zip(cols, covered):
        run = run + 1 if (on and not cov) else 0
        best = max(best, run)
    return best
