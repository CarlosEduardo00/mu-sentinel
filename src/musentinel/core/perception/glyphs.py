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
MARGIN_MIN = 0.06  # vantagem mínima do caractere escolhido sobre o 2º colocado
STRONG_SCORE = 0.93  # a partir daqui o casamento é quase perfeito…
MARGIN_STRONG = 0.03  # …e basta uma vantagem menor


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

    def line_height(self) -> int | None:
        hs = [v.image.shape[0] for vs in self.glyphs.values() for v in vs]
        if len(hs) < 5:
            return None
        return int(np.bincount(hs).argmax())

    def add(self, g: Glyph) -> None:
        lh = self.line_height()
        if lh is not None and abs(g.image.shape[0] - lh) > 1:
            return  # altura fora do padrão: recorte pegou brilho do fundo
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
_WIDTH = {",": (0.2, 0.8), ":": (0.2, 0.8), ".": (0.2, 0.8), "/": (0.35, 1.3), "1": (0.3, 0.9)}
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
    # recorte com largura fora do normal = corte errado; não pode virar modelo
    digit_w = [p.shape[1] for c, p in zip(chars, parts) if c.isdigit() and c != "1"]
    med = float(np.median(digit_w)) if digit_w else None
    added = False
    for c, img in zip(chars, parts):
        if med is not None:
            w = img.shape[1]
            lo, hi = (_WIDTH.get(c, _DIGIT_W))
            if not (lo * med - 1 <= w <= hi * med * 0.9 + 1):
                continue
        font.add(Glyph(c, img))
        added = True
    return added


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
    text, conf, _ = read_text_ex(roi_bgr, font, charset)
    return text, conf


def read_text_ex(
    roi_bgr: np.ndarray, font: GlyphFont, charset: str | None = None, debug: list | None = None,
    info: dict | None = None,
) -> tuple[str, float, tuple[int, int] | None]:
    """Como read_text, mas também devolve a extensão horizontal (x0, x1) do texto lido.

    `debug` (lista) recebe o motivo de cada recusa — usado só para diagnóstico.
    `info` (dict) recebe 'line': (y0, y1) da linha de texto lida.
    """
    log = debug.append if debug is not None else (lambda _m: None)
    im = ink(roi_bgr)
    if float(im.max()) - float(im.min()) < 30:  # sem contraste: não há texto
        return "", 0.0, None

    hits: list[Hit] = []
    scored: list[tuple[str, int, np.ndarray]] = []  # (caractere, largura, pontuação por coluna)
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
            scored.append((ch, tw, col))
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
        return "", 0.0, None
    # todos os caracteres de uma leitura estão na mesma linha (modelos têm a altura da linha)
    # compara o meio de cada caractere: modelos podem ter alturas um pouco diferentes
    strong = sorted(chosen, key=lambda h: h.score, reverse=True)[: max(1, len(chosen) // 2)]
    line_mid = float(np.median([h.y + h.h / 2 for h in strong]))
    for h in chosen:
        if abs(h.y + h.h / 2 - line_mid) > LINE_TOL:
            log(f"fora da linha: {h}")
    chosen = [h for h in chosen if abs(h.y + h.h / 2 - line_mid) <= LINE_TOL]
    line_y = int(min(h.y for h in chosen)) if chosen else 0
    if not chosen:
        return "", 0.0, None
    chosen.sort(key=lambda h: h.x)
    extent = (chosen[0].x, chosen[-1].x + chosen[-1].w)
    text = "".join(h.char for h in chosen)
    conf = min(h.score for h in chosen)
    if info is not None:
        info["line"] = (line_y, line_y + max(h.h for h in chosen))
        info["chars"] = [(h.x, h.w, h.char) for h in chosen]

    # Margem: se outro caractere pontua quase igual no mesmo lugar (6 × 8, 2 × 8),
    # a leitura é ambígua e não pode sair confiante.
    # O rival conta mesmo abaixo de MATCH_MIN: um '6' mal modelado a 0,81 contra
    # um '8' a 0,86 é ambíguo. Só disputam caracteres de largura parecida (um '1'
    # estreito "cabe" dentro da haste de qualquer dígito e não é rival de verdade).
    for c in chosen:
        lo, hi = max(0, c.x - 1), c.x + 2
        rival = max(
            (
                float(col[lo:hi].max())
                for ch, tw, col in scored
                if ch != c.char and abs(tw - c.w) <= 2 and col[lo:hi].size
            ),
            default=0.0,
        )
        # casamento quase perfeito é confiável com margem menor
        need = MARGIN_STRONG if c.score >= STRONG_SCORE else MARGIN_MIN
        if c.score - rival < need:
            log(f"ambíguo: {c.char}@{c.x} {c.score:.2f} × rival {rival:.2f}")
            conf = min(conf, 0.5)

    # Toda tinta da linha precisa estar explicada por algum caractere. Se sobrar
    # um trecho com tinta sem caractere (dígito desconhecido), a leitura não vale:
    # melhor "ilegível" do que um número com um dígito a menos.
    if _uncovered_ink(im, chosen, line_y) >= UNCOVERED_MAX:
        log(f"tinta sem caractere; escolhidos {[(h.char, h.x, h.w, round(h.score, 2)) for h in chosen]}")
        return text, min(conf, 0.3), extent
    return text, conf, extent


UNCOVERED_MAX = 3  # colunas seguidas com tinta e sem caractere
SMALL_FONT_H = 12  # altura de linha (px) a partir da qual a fonte é "grande" (1280x960)
EDGE_COLS = 3  # texto a até 3 px da borda da área: o número pode continuar do lado de fora


def _stroke_cols(band: np.ndarray) -> np.ndarray:
    """Colunas com traço de letra na faixa da linha de texto (respingo de magia ao fundo é baixinho)."""
    h = band.shape[0]
    peak = float(band.max()) if band.size else 0.0
    if h <= SMALL_FONT_H:
        # fonte pequena (janela 800x600): traço de 1 px, mais apagado pelo antisserrilhado
        thr, min_px = max(60.0, 0.45 * peak), 2
    else:
        thr, min_px = max(100.0, 0.6 * peak), max(2, int(0.3 * h))
    return (band >= thr).sum(axis=0) >= min_px


def near_edges(roi_bgr: np.ndarray, extent: tuple[int, int] | None,
               line: tuple[int, int] | None, cols: int = EDGE_COLS) -> tuple[bool, bool]:
    """O texto lido encosta (ou quase) na borda esquerda / direita da área?

    Junta a posição dos caracteres lidos com traço de tinta na borda: um "1" cortado ao meio
    não vira caractere, mas deixa tinta na beirada. Encostar = o número pode continuar fora
    da área (HP 1200 numa área feita para "980/980" vira "200").
    """
    if extent is None:
        return False, False
    w = roi_bgr.shape[1]
    left, right = extent[0] <= cols, extent[1] >= w - cols
    if line is not None and not (left and right):
        band = ink(roi_bgr)[line[0]:line[1]]
        if band.size:
            # sensível de propósito (o miolo de um "0" cortado tem só 2 px claros por coluna): disparar à
            # toa custa só uma releitura, que não acha caractere novo e fica com a leitura de antes
            thr = max(90.0, 0.5 * float(band.max()))
            col_max = band.max(axis=0)
            left = left or bool((col_max[:cols] >= thr).any())
            right = right or bool((col_max[-cols:] >= thr).any())
    return left, right


def attached(chars: list[tuple[int, int, str]], span: tuple[int, int], max_gap: int) -> bool:
    """Os caracteres fora de `span` (achados ao ampliar a área) estão colados no número, em sequência?
    Algo solto a vários px (arte do orbe, outro texto) não faz parte dele. A "/" do EXP tem espaço
    em volta ("81186 / 1316440"): perto dela vale um espaço maior."""
    inside = [c for c in chars if c[0] + c[1] > span[0] + 1 and c[0] < span[1] - 1]
    left = sorted((c for c in chars if c[0] + c[1] <= span[0] + 1), key=lambda c: -c[0])
    right = sorted((c for c in chars if c[0] >= span[1] - 1), key=lambda c: c[0])

    def ok(gap: int, a: str, b: str) -> bool:
        return gap <= (3 * max_gap if "/" in (a, b) else max_gap)

    edge, nb = span[0], (min(inside)[2] if inside else "")
    for x, w, ch in left:  # do número para fora
        if not ok(edge - (x + w), ch, nb):
            return False
        edge, nb = x, ch
    edge, nb = span[1], (max(inside)[2] if inside else "")
    for x, w, ch in right:
        if not ok(x - edge, nb, ch):
            return False
        edge, nb = x + w, ch
    return True


def digit_width(font: GlyphFont) -> int:
    """Largura típica de um dígito na fonte (px)."""
    ws = [g.image.shape[1] for c, vs in font.glyphs.items() if c.isdigit() and c != "1" for g in vs]
    return int(np.median(ws)) if ws else 8


def _uncovered_ink(im: np.ndarray, chosen: list[Hit], line_y: int) -> int:
    h = max(c.h for c in chosen)
    cols = _stroke_cols(im[line_y : line_y + h])
    covered = np.zeros_like(cols)
    for c in chosen:
        covered[max(0, c.x - 1) : c.x + c.w + 1] = True
    run = best = 0
    for on, cov in zip(cols, covered):
        run = run + 1 if (on and not cov) else 0
        best = max(best, run)
    return best
