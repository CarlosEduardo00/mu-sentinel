"""Calibração automática do HUD, janela por janela.

O OCR da tela inteira (lento, mas não precisa de calibração) acha os textos do HUD: mapa,
coordenadas, HP, EXP e o tempo de caça (no Instant Hunting Log, onde quer que ele esteja).
Esses valores viram o gabarito para:
  - criar as regiões (ROIs) de um tamanho de janela que ainda não tem perfil;
  - aumentar uma região quando o texto aparece fora dela (número mais comprido etc.);
  - ensinar ao leitor rápido (modelo de dígitos) os caracteres que ele ainda erra.
Só aprende com valores que fazem sentido (HP atual ≤ máximo, coordenadas ≤ 255...).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np

from .fields import PARSERS
from .ocr import DEFAULT_MAPS, OcrEngine, TextBox, match_name
from .panels import PanelHit
from .profile import CHARSETS, Profile, Roi
from .reader import HudReader
from .training import learn_sample

log = logging.getLogger(__name__)

_RATIO = re.compile(r"^(\d{1,9})\s*/\s*(\d{1,10})$")
_COORDS = re.compile(r"^(\d{1,3})[,.](\d{1,3})$")
_TIME = re.compile(r"(\d{2,3}:\d{2}:\d{2})")

# hunting time em relação ao centro do título "Instant Hunting Log" (px em 800x600)
HT_REL = (38, 21, 108, 43)  # x0, y0, x1, y1


@dataclass
class CalResult:
    found: dict[str, str] = field(default_factory=dict)  # campo → valor lido pelo OCR completo
    learned: list[str] = field(default_factory=list)  # campos cujo leitor rápido aprendeu algo
    moved: list[str] = field(default_factory=list)  # regiões criadas ou aumentadas
    missing: list[str] = field(default_factory=list)  # não achados na tela (menu por cima, painel fechado)
    created: bool = False  # perfil novo para este tamanho

    def summary(self) -> str:
        names = {"hp": "HP", "exp": "EXP", "map": "Mapa", "coords": "Coordenadas", "hunting_time": "Tempo de caça"}
        lines = []
        if self.found:
            lines.append("Lido agora: " + " · ".join(f"{names.get(k, k)} {v}" for k, v in self.found.items()))
        if self.created:
            lines.append("Perfil novo criado para este tamanho de janela.")
        if self.learned:
            lines.append("Aprendeu: " + ", ".join(names.get(k, k) for k in self.learned))
        if self.moved:
            lines.append("Regiões ajustadas: " + ", ".join(names.get(k, k) for k in self.moved))
        if self.missing:
            lines.append("Não achei na tela: " + ", ".join(names.get(k, k) for k in self.missing)
                         + " (menu por cima ou painel fechado?)")
        if not self.learned and not self.moved and not self.created and self.found:
            lines.append("Nada a corrigir: o leitor já lê tudo certo nesta janela.")
        return "\n".join(lines)


def hunting_time_roi(hit: PanelHit, size: tuple[int, int]) -> Roi:
    """Região do valor do Hunting Time dentro do Instant Hunting Log desta janela."""
    w, h = size
    x0, y0 = hit.rel(HT_REL[0], HT_REL[1])
    x1, y1 = hit.rel(HT_REL[2], HT_REL[3])
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    return Roi(x=x0, y=y0, w=max(1, x1 - x0), h=max(1, y1 - y0))


def _norm_ratio(text: str) -> str | None:
    m = _RATIO.match(text.replace(" ", ""))
    return f"{int(m.group(1))}/{int(m.group(2))}" if m else None


def find_hud(img: np.ndarray, boxes: list[TextBox], profile: Profile | None,
             caca: PanelHit | None = None, maps: list[str] | None = None) -> dict[str, tuple[str, TextBox]]:
    """Acha o texto de cada campo do HUD entre as caixas do OCR da tela inteira."""
    h, w = img.shape[:2]
    maps = maps or DEFAULT_MAPS
    out: dict[str, tuple[str, TextBox]] = {}

    def near_roi(name: str, cands: list[TextBox]) -> TextBox | None:
        roi = profile.rois.get(name) if profile else None
        if roi is None or not cands:
            return None
        cx, cy = roi.x + roi.w / 2, roi.y + roi.h / 2
        best = min(cands, key=lambda b: (b.cx - cx) ** 2 + (b.cy - cy) ** 2)
        if abs(best.cx - cx) <= max(roi.w, 40) and abs(best.cy - cy) <= max(roi.h * 2, 20):
            return best
        return None

    # mapa e coordenadas: canto de cima à esquerda
    top = [b for b in boxes if b.cy < 0.08 * h and b.cx < 0.45 * w]
    maps_found = []
    for b in top:
        name, ratio = match_name(b.text, maps, cutoff=0.8)
        if name:
            maps_found.append((ratio * b.score, name, b))
    if maps_found:
        _, name, mb = max(maps_found, key=lambda t: t[0])
        out["map"] = (name, mb)
        row = [b for b in top if b.x0 >= mb.x1 - 2 and abs(b.cy - mb.cy) <= 0.6 * mb.h + 2]
        for b in sorted(row, key=lambda b: b.x0):
            m = _COORDS.match(b.text.replace(" ", ""))
            if m and int(m.group(1)) <= 255 and int(m.group(2)) <= 255:
                out["coords"] = (f"{int(m.group(1))},{int(m.group(2))}", b)
                break

    # HP: número "a/b" no orbe vermelho (embaixo, à esquerda; o SD/AG fica mais à direita e acima)
    ratios = [(b, _norm_ratio(b.text)) for b in boxes]
    ratios = [(b, t) for b, t in ratios if t]
    hp_c = [b for b, _ in ratios if 0.85 * h < b.cy < 0.97 * h and b.cx < 0.35 * w]
    hb = near_roi("hp", hp_c) or (min(hp_c, key=lambda b: b.cx) if hp_c else None)
    if hb is not None:
        out["hp"] = (_norm_ratio(hb.text), hb)

    # EXP: "a / b" bem embaixo, perto do meio. O OCR às vezes devolve os dois números separados.
    bottom = [b for b in boxes if b.cy > 0.96 * h and 0.2 * w < b.cx < 0.8 * w]
    exp_c = [b for b in bottom if _norm_ratio(b.text)]
    nums = sorted((b for b in bottom if re.fullmatch(r"\d{2,10}", b.text.replace(" ", ""))), key=lambda b: b.x0)
    for a, c in zip(nums, nums[1:]):
        gap = c.x0 - a.x1
        if 0 <= gap <= 4 * max(a.h, c.h) and abs(a.cy - c.cy) <= 0.6 * max(a.h, c.h) \
                and int(a.text.replace(" ", "")) <= int(c.text.replace(" ", "")):
            exp_c.append(TextBox(a.x0, min(a.y0, c.y0), c.x1, max(a.y1, c.y1),
                                 f"{a.text.strip()}/{c.text.strip()}", min(a.score, c.score)))
    eb = near_roi("exp", exp_c) or (min(exp_c, key=lambda b: abs(b.cx - w / 2)) if exp_c else None)
    if eb is not None:
        out["exp"] = (_norm_ratio(eb.text), eb)

    # tempo de caça: valor ao lado de "Hunting Time" (no Instant Hunting Log desta janela)
    for b in boxes:
        if b.key.startswith("huntingtime"):
            tol = max(6.0, 0.6 * b.h)
            row = [v for v in boxes if v is not b and abs(v.cy - b.cy) <= tol and v.x0 >= b.x1 - 2]
            for v in sorted(row, key=lambda v: -v.x1):
                m = _TIME.search(v.text.replace(" ", ""))
                if m:
                    out["hunting_time"] = (m.group(1), v)
                    break
            break

    # só fica o que faz sentido
    for name in list(out):
        if name in PARSERS and not PARSERS[name](out[name][0], 1.0).ok:
            out.pop(name)
    return out


def _grow(name: str, roi: Roi | None, b: TextBox, size: tuple[int, int]) -> Roi | None:
    """Região que cabe o texto achado, com folga para números mais compridos. None = já cabe."""
    w, h = size
    if roi is not None:
        # a caixa do OCR sobra uns pixels em volta do texto: só mexe se passar disso
        slack = 4
        if roi.x <= b.x0 + slack and roi.y <= b.y0 + slack and roi.x + roi.w >= b.x1 - slack \
                and roi.y + roi.h >= b.y1 - slack:
            return None
        # região conhecida: estica só o necessário (região larga demais atrapalha a leitura)
        nx0, ny0 = max(0, min(roi.x, b.x0 - 2)), max(0, min(roi.y, b.y0 - 1))
        nx1, ny1 = min(w, max(roi.x + roi.w, b.x1 + 2)), min(h, max(roi.y + roi.h, b.y1 + 1))
        return Roi(x=nx0, y=ny0, w=nx1 - nx0, h=ny1 - ny0)
    # tamanho novo: região justa (arte do orbe/barra em volta atrapalha o OCR de confirmação), com
    # folga só na largura para números um pouco mais compridos; a próxima calibração estica se precisar
    pad_y = 2
    if name == "coords":  # alinhado à esquerda, logo depois do nome do mapa
        x0, x1 = b.x0 - 3, b.x1 + int(0.3 * (b.x1 - b.x0)) + 3
    else:  # centralizado (orbe, barra de EXP, nome do mapa)
        half = 0.5 * (b.x1 - b.x0) * (1.6 if name == "map" else 1.2) + 3
        x0, x1 = int(b.cx - half), int(b.cx + half)
    x0, y0 = max(0, x0), max(0, b.y0 - pad_y)
    return Roi(x=x0, y=y0, w=min(w, x1) - x0, h=min(h, b.y1 + pad_y) - y0)


def calibrate(img: np.ndarray, ocr: OcrEngine, profile: Profile | None, boxes: list[TextBox] | None = None,
              caca: PanelHit | None = None, passes: int = 2) -> tuple[Profile, CalResult]:
    """Calibra o perfil do tamanho desta janela com o que o OCR completo leu nela.

    Devolve o perfil (novo ou o mesmo, alterado) e o resumo. Não salva em disco.
    """
    h, w = img.shape[:2]
    res = CalResult()
    if profile is not None and tuple(profile.client_size) != (w, h):
        raise ValueError(f"perfil {profile.client_size} não é do tamanho da janela {w}x{h}")
    if profile is None:
        profile = Profile(name=f"{w}x{h}", client_size=(w, h))
        res.created = True
    boxes = boxes if boxes is not None else ocr.detect(img)
    labels = find_hud(img, boxes, profile, caca)
    res.found = {k: v for k, (v, _) in labels.items()}
    res.missing = [k for k in ("hp", "exp", "map", "coords", "hunting_time") if k not in labels]

    for name, (_, b) in labels.items():
        if name == "hunting_time" and caca is not None:
            new = hunting_time_roi(caca, (w, h))  # posição deste painel (cada janela tem o seu lugar)
            old = profile.rois.get(name)
            if old is None or (old.x, old.y, old.w, old.h) != (new.x, new.y, new.w, new.h):
                profile.rois[name] = new
                profile.extents.pop(name, None)
                res.moved.append(name)
            continue
        new = _grow(name, profile.rois.get(name), b, (w, h))
        if new is not None:
            profile.rois[name] = new
            profile.extents.pop(name, None)  # posição habitual do texto mudou junto com a região
            res.moved.append(name)

    expected = {k: v for k, (v, _) in labels.items()}
    # texto que o OCR da tela inteira não achou (ex.: EXP sobre a barra verde): lê a própria região
    # com o OCR em duas escalas; só vale se as duas concordarem e o valor fizer sentido
    for name in ("hp", "exp", "coords"):
        roi = profile.rois.get(name)
        if name in expected or roi is None:
            continue
        text, score = ocr.read_number(roi.crop(img), CHARSETS[name])
        if text and score >= 0.9 and PARSERS[name](text, score).ok:
            expected[name] = res.found[name] = text
            res.missing.remove(name)
    reader = HudReader(profile, ocr=ocr, ocr_fallback=False)
    learned: set[str] = set()
    for _ in range(passes):
        learned.update(learn_sample(profile, reader, img, expected))
    res.learned = [k for k in ("hp", "exp", "coords", "hunting_time", "map") if k in learned]
    log.info("calibração automática %dx%d: lido %s · aprendeu %s · regiões %s · faltou %s", w, h, res.found,
             res.learned, res.moved, res.missing)
    return profile, res
