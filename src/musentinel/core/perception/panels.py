"""Painéis do jogo que o usuário deixa abertos: Personagem (C), Inventário (I), Instant Hunting Log
e Gremory Case (aba Personal Shop, no slot "Loja").

O MU Sentinel só olha a imagem: quem abre e arruma as janelas no jogo é o usuário. Cada painel é
achado pelo texto do título em qualquer lugar da tela (as janelas podem ser arrastadas) e o resto é
medido a partir dele. As medidas vêm do client em 800x600; em outra resolução a escala sai da altura
do texto do título.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from .ocr import OcrEngine, TextBox

KINDS = ("personagem", "inventario", "caca", "loja")
LABEL = {
    "personagem": "Personagem (C)",
    "inventario": "Inventário (I)",
    "caca": "Caçada (Instant Hunting Log)",
    "loja": "Gremory Case",
}
HOW_TO_OPEN = {
    "personagem": "abra com C no jogo e deixe aberto",
    "inventario": "abra com I no jogo e deixe aberto",
    "caca": "deixe aberta a janela Instant Hunting Log",
    "loja": "abra o Gremory Case na aba Personal Shop e deixe aberto",
}


@dataclass(frozen=True)
class _Anchor:
    key: str  # texto normalizado (ver TextBox.key)
    dx: float  # do centro da âncora até o ponto de referência do painel (px em 800x600)
    dy: float
    ref_h: float  # altura da caixa de texto da âncora em 800x600


@dataclass(frozen=True)
class _Spec:
    anchors: tuple[_Anchor, ...]
    rect: tuple[float, float, float, float]  # x0, y0, x1, y1 a partir do ponto de referência


SPECS: dict[str, _Spec] = {
    # ponto de referência = centro do título "Inventory"
    "inventario": _Spec((_Anchor("inventory", 0, 0, 17),), (-127, -19, 121, 477)),
    # centro do título "Gremory Case"
    "loja": _Spec((_Anchor("gremorycase", 0, 0, 17),), (-150, -21, 145, 476)),
    # centro do título "Instant Hunting Log"
    "caca": _Spec((_Anchor("instanthuntinglog", 0, 0, 14),), (-101, -11, 110, 151)),
    # centro do rótulo "Class" (o título é o nome do personagem, que muda)
    "personagem": _Spec((_Anchor("class", 0, 0, 14), _Anchor("ptsremaining", -19.5, -64.5, 17),
                         _Anchor("strength", -6, -128, 16)), (-32, -84, 250, 389)),
}

# Inventário: grade 8x8 a partir do título
INV_GRID = (-115.5, 260.5, 21.6, 8, 8)  # x0, y0, lado da célula, colunas, linhas
INV_ZEN_BAND = (440, 475)  # faixa (y) da linha do Zen
# Gremory Case: abas e contador "0 / 150"
SHOP_TABS_Y = (96, 116)
SHOP_TABS_X = ((-127, -67), (-63, -2), (0, 64), (66, 126))  # Character, My Server, MU Mobile, Personal Shop
SHOP_PERSONAL_TAB = 3
SHOP_COUNTER_BAND = (430, 475)


@dataclass
class PanelHit:
    kind: str
    rect: tuple[int, int, int, int]  # x0, y0, x1, y1 na imagem (já recortado à imagem)
    ref: tuple[float, float]
    scale: float
    anchor: TextBox
    anchor_img: np.ndarray | None = field(default=None, repr=False)  # para conferir sem OCR

    def rel(self, dx: float, dy: float) -> tuple[int, int]:
        return int(round(self.ref[0] + dx * self.scale)), int(round(self.ref[1] + dy * self.scale))


def _scale(h: float, ref_h: float) -> float:
    s = h / ref_h if ref_h else 1.0
    return 1.0 if 0.75 <= s <= 1.3 else s  # a altura da caixa do OCR varia uns pixels


def _matches(key: str, want: str) -> bool:
    if key == want:
        return True
    if len(want) < 8:
        return False
    return difflib.SequenceMatcher(None, key, want).ratio() >= 0.85


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def _anchor_crop(img: np.ndarray, b: TextBox, pad: int = 3) -> np.ndarray | None:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, b.x0 - pad), max(0, b.y0 - pad), min(w, b.x1 + pad), min(h, b.y1 + pad)
    if x1 - x0 < 8 or y1 - y0 < 6:
        return None
    return _gray(img[y0:y1, x0:x1]).copy()


def locate(img: np.ndarray, boxes: list[TextBox], kinds=KINDS) -> dict[str, PanelHit]:
    """Acha os painéis abertos a partir das caixas de texto da tela inteira."""
    h, w = img.shape[:2]
    keys = [(b, b.key) for b in boxes]
    found: dict[str, PanelHit] = {}
    for kind in kinds:
        spec = SPECS[kind]
        for a in spec.anchors:
            cands = [b for b, k in keys if _matches(k, a.key)]
            if kind == "inventario":  # o botão "Event Inventory" do canto também diz "Inventory"
                cands = [b for b in cands if not any(
                    k2.startswith("event") and abs(b2.cx - b.cx) < 50 and -24 < b2.cy - b.cy < 4 and b2 is not b
                    for b2, k2 in keys)]
            if kind == "personagem" and a.key == "class":  # "Class" sozinho é comum: exige "Level" logo abaixo
                cands = [b for b in cands if any(
                    k2.startswith("level") and abs(b2.x0 - b.x0) < 12 and 5 < b2.cy - b.cy < 30 for b2, k2 in keys)]
            if not cands:
                continue
            b = max(cands, key=lambda c: c.score)
            s = _scale(b.h, a.ref_h)
            ref = (b.cx + a.dx * s, b.cy + a.dy * s)
            x0, y0, x1, y1 = spec.rect
            rect = (max(0, int(ref[0] + x0 * s)), max(0, int(ref[1] + y0 * s)),
                    min(w, int(ref[0] + x1 * s)), min(h, int(ref[1] + y1 * s)))
            if rect[2] - rect[0] < 40 or rect[3] - rect[1] < 40:
                continue
            found[kind] = PanelHit(kind, rect, ref, s, b, _anchor_crop(img, b))
            break
    return found


def still_open(img: np.ndarray, hit: PanelHit, min_score: float = 0.8) -> bool:
    """Confere, sem OCR, se o título/âncora continua no mesmo lugar."""
    if hit.anchor_img is None:
        return False
    th, tw = hit.anchor_img.shape[:2]
    b = hit.anchor
    pad = 6
    h, w = img.shape[:2]
    x0, y0 = max(0, b.x0 - 3 - pad), max(0, b.y0 - 3 - pad)
    x1, y1 = min(w, b.x1 + 3 + pad), min(h, b.y1 + 3 + pad)
    region = _gray(img[y0:y1, x0:x1])
    if region.shape[0] < th or region.shape[1] < tw:
        return False
    score = float(cv2.matchTemplate(region, hit.anchor_img, cv2.TM_CCOEFF_NORMED).max())
    return score >= min_score


def crop(img: np.ndarray, hit: PanelHit) -> np.ndarray:
    x0, y0, x1, y1 = hit.rect
    return img[y0:y1, x0:x1].copy()


# ---------------------------------------------------------------------- números
_THOUSANDS = re.compile(r"^\d{1,3}([.,]\d{3})+$")


def parse_number(text: str) -> float | None:
    """'186.734.144' / '2,444' → milhares; '0.07' → decimal (o OCR troca vírgula por ponto)."""
    t = re.sub(r"[^\d.,]", "", text or "")
    if not t or not any(c.isdigit() for c in t):
        return None
    if _THOUSANDS.match(t):
        return float(re.sub(r"[.,]", "", t))
    t = t.replace(",", ".")
    if t.count(".") > 1:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def fmt_int(v: float | None) -> str:
    return "—" if v is None else f"{int(round(v)):,}".replace(",", ".")


def fmt_big(v: float | None) -> str:
    """8_800_000 → '8,8 mi'."""
    if v is None:
        return "—"
    for div, suf in ((1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if abs(v) >= div:
            return f"{v / div:.1f}".replace(".", ",") + f" {suf}"
    return f"{v:.0f}"


def fmt_dec(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 10 or float(v).is_integer():
        return fmt_int(v)
    return f"{v:.2f}".replace(".", ",")


# ---------------------------------------------------------------------- leituras
@dataclass
class PanelReading:
    kind: str
    hit: PanelHit
    image: np.ndarray = field(repr=False)  # recorte do painel
    fields: dict[str, str] = field(default_factory=dict)  # rótulo em pt-BR → valor, na ordem de exibição
    lines: list[str] = field(default_factory=list)  # texto livre lido no painel
    data: dict = field(default_factory=dict)  # valores numéricos (para comparar entre leituras)

    def summary(self) -> str:
        parts = [f"{k}: {v}" for k, v in self.fields.items()]
        return "\n".join(parts) if parts else "(não consegui ler o texto do painel)"


def _boxes_in(boxes: list[TextBox], hit: PanelHit) -> list[TextBox]:
    x0, y0, x1, y1 = hit.rect
    return [b for b in boxes if x0 <= b.cx <= x1 and y0 <= b.cy <= y1]


def _row_value(label: TextBox, boxes: list[TextBox], rightmost: bool = False) -> TextBox | None:
    tol = max(6.0, 0.6 * label.h)
    row = [b for b in boxes if b is not label and abs(b.cy - label.cy) <= tol and b.x0 >= label.x1 - 2]
    if not row:
        return None
    return max(row, key=lambda b: b.x1) if rightmost else min(row, key=lambda b: b.x0)


def inventory_cells(img: np.ndarray, hit: PanelHit) -> list[list[bool]] | None:
    """Grade do inventário: True = célula ocupada (ícone ou fundo de item)."""
    gx, gy, cell, cols, rows = INV_GRID
    s = hit.scale
    x0, y0 = hit.ref[0] + gx * s, hit.ref[1] + gy * s
    c = cell * s
    h, w = img.shape[:2]
    if x0 < 0 or y0 < 0 or x0 + cols * c > w or y0 + rows * c > h:
        return None
    inset = max(2, int(round(c * 0.18)))
    grid = []
    for r in range(rows):
        row = []
        for k in range(cols):
            a = img[int(y0 + r * c) + inset:int(y0 + (r + 1) * c) - inset + 1,
                    int(x0 + k * c) + inset:int(x0 + (k + 1) * c) - inset + 1].astype(np.float32)
            empty = a.size and float(a.std()) < 12 and float(a.mean()) < 45
            row.append(not empty)
        grid.append(row)
    return grid


def read_inventory(img: np.ndarray, hit: PanelHit, boxes: list[TextBox]) -> PanelReading:
    r = PanelReading("inventario", hit, crop(img, hit))
    grid = inventory_cells(img, hit)
    if grid is not None:
        total = sum(len(row) for row in grid)
        used = sum(sum(row) for row in grid)
        r.data.update(used=used, total=total, grid=grid)
        r.fields["Espaços"] = f"{used} ocupados · {total - used} livres (de {total})"
    zen = None
    lo, hi = INV_ZEN_BAND
    for b in _boxes_in(boxes, hit):
        dy = (b.cy - hit.ref[1]) / hit.scale
        if lo <= dy <= hi and b.cx < hit.ref[0]:
            v = parse_number(b.text)
            if v is not None and (zen is None or v > zen):
                zen = v
    if zen is not None:
        r.data["zen"] = zen
        r.fields["Zen"] = fmt_int(zen)
    return r


CHAR_FIELDS = (  # rótulo do jogo (normalizado) → rótulo em pt-BR
    ("class", "Classe"), ("level", "Level"), ("masterlevel", "Master Level"),
    ("ptsremaining", "Pontos a distribuir"), ("strength", "Força"), ("agility", "Agilidade"),
    ("stamina", "Vitalidade"), ("vitality", "Vitalidade"), ("energy", "Energia"), ("command", "Comando"),
)
_TEXT_FIELDS = {"class"}


def read_character(img: np.ndarray, hit: PanelHit, boxes: list[TextBox]) -> PanelReading:
    r = PanelReading("personagem", hit, crop(img, hit))
    inside = _boxes_in(boxes, hit)
    # título da janela = nome do personagem (faixa de cima do painel)
    top = [b for b in inside if (b.cy - hit.rect[1]) < 30 * hit.scale and b.h >= 8]
    if top:
        r.data["nome"] = max(top, key=lambda b: b.x1 - b.x0).text
    for key, label in CHAR_FIELDS:
        if label in r.fields:
            continue
        lab = next((b for b in inside if b.key == key), None)
        if lab is None:
            continue
        val = _row_value(lab, inside)
        if val is None:
            continue
        if key in _TEXT_FIELDS:
            r.fields[label] = val.text
        else:
            m = re.search(r"\d[\d.,]*", val.text)
            if not m:
                continue
            num = parse_number(m.group(0))
            r.fields[label] = m.group(0) if num is None else fmt_int(num)
            if num is not None:
                r.data[key] = num
    return r


HUNT_FIELDS = (  # começo do rótulo (normalizado) → rótulo em pt-BR
    ("huntingtime", "Tempo de caça"), ("gainedexp", "EXP por segundo"), ("monsterkills", "Abates por segundo"),
    ("normaldmg", "Dano por segundo"), ("elementaldmg", "Dano elemental por segundo"),
    ("healamount", "Cura por segundo"),
)


def parse_hms(text: str) -> int | None:
    m = re.search(r"(\d{1,3}):(\d{2}):(\d{2})", text or "")
    if not m:
        return None
    h, mi, s = map(int, m.groups())
    return h * 3600 + mi * 60 + s


def read_hunting(img: np.ndarray, hit: PanelHit, boxes: list[TextBox]) -> PanelReading:
    r = PanelReading("caca", hit, crop(img, hit))
    inside = [b for b in _boxes_in(boxes, hit) if b is not hit.anchor and b.key != hit.anchor.key]
    for key, label in HUNT_FIELDS:
        lab = next((b for b in inside if b.key.startswith(key)), None)
        if lab is None:
            continue
        val = _row_value(lab, inside, rightmost=True)
        if val is None:
            continue
        if key == "huntingtime":
            secs = parse_hms(val.text)
            if secs is not None:
                r.data["tempo_s"] = secs
                r.fields[label] = val.text.strip()
            continue
        num = parse_number(val.text)
        if num is None:
            continue
        r.data[key] = num
        r.fields[label] = fmt_dec(num)
    if "gainedexp" in r.data:
        r.fields["EXP por hora (estimado)"] = fmt_big(r.data["gainedexp"] * 3600)
    if "monsterkills" in r.data:
        r.fields["Abates por hora (estimado)"] = fmt_int(r.data["monsterkills"] * 3600)
    return r


def shop_selected_tab(img: np.ndarray, hit: PanelHit) -> int | None:
    """Índice da aba selecionada do Gremory Case (a selecionada é avermelhada/laranja)."""
    y0, y1 = (int(hit.ref[1] + v * hit.scale) for v in SHOP_TABS_Y)
    reds = []
    for a, b in SHOP_TABS_X:
        x0, x1 = int(hit.ref[0] + a * hit.scale), int(hit.ref[0] + b * hit.scale)
        reg = img[max(0, y0):y1, max(0, x0):x1].reshape(-1, 3).astype(np.float32)
        if not reg.size:
            return None
        bgr = reg.mean(0)
        reds.append(float(bgr[2] - bgr[0]))
    best = int(np.argmax(reds))
    others = [v for i, v in enumerate(reds) if i != best]
    return best if reds[best] - max(others) > 20 else None


_COUNTER = re.compile(r"(\d+)\s*/\s*(\d+)")


def read_shop(img: np.ndarray, hit: PanelHit, boxes: list[TextBox]) -> PanelReading:
    r = PanelReading("loja", hit, crop(img, hit))
    tab = shop_selected_tab(img, hit)
    r.data["aba"] = tab
    r.data["aba_ok"] = tab == SHOP_PERSONAL_TAB
    r.fields["Aba"] = "Personal Shop" if tab == SHOP_PERSONAL_TAB else "outra aba (selecione Personal Shop)"
    lo, hi = SHOP_COUNTER_BAND
    for b in _boxes_in(boxes, hit):
        dy = (b.cy - hit.ref[1]) / hit.scale
        m = _COUNTER.search(b.text.replace(" ", ""))
        if lo <= dy <= hi and m:
            count, cap = int(m.group(1)), int(m.group(2))
            if cap >= count:
                r.data.update(count=count, cap=cap)
                r.fields["Itens no Gremory Case"] = f"{count} / {cap}"
            break
    return r


READERS = {"inventario": read_inventory, "personagem": read_character, "caca": read_hunting, "loja": read_shop}


def read(kind: str, img: np.ndarray, hit: PanelHit, ocr: OcrEngine,
         boxes: list[TextBox] | None = None) -> PanelReading:
    """Lê um painel já localizado. Sem as caixas da tela inteira, faz OCR só do recorte do painel."""
    if boxes is None:
        x0, y0 = hit.rect[0], hit.rect[1]
        boxes = [b.shifted(x0, y0) for b in ocr.detect(crop(img, hit))]
    return READERS[kind](img, hit, boxes)


def scan(img: np.ndarray, ocr: OcrEngine, kinds=KINDS) -> tuple[dict[str, PanelHit], list[TextBox]]:
    """Procura os painéis na tela inteira (OCR da imagem toda: 1–3 s). Devolve também as caixas lidas."""
    boxes = ocr.detect(img)
    return locate(img, boxes, kinds), boxes


def read_shop_counter(img: np.ndarray, hit: PanelHit, ocr: OcrEngine) -> tuple[int, int] | None:
    """Só o contador "N / 150" do Gremory Case (OCR de uma faixa pequena: barato)."""
    lo, hi = SHOP_COUNTER_BAND
    x0, y0 = hit.rel(-70, lo)
    x1, y1 = hit.rel(70, hi)
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if x1 - x0 < 20 or y1 - y0 < 10:
        return None
    for b in ocr.detect(img[y0:y1, x0:x1]):
        m = _COUNTER.search(b.text.replace(" ", ""))
        if m and int(m.group(2)) >= int(m.group(1)):
            return int(m.group(1)), int(m.group(2))
    return None
