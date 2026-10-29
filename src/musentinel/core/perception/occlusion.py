"""Casos sintéticos de HUD coberto (menu, janela, inventário por cima).

Pega um print rotulado e cobre cada campo numérico — inteiro, metade da
esquerda ou metade da direita — com um retângulo escuro ou claro com textura,
imitando janelas do jogo. Em nenhum desses casos o leitor pode afirmar um
valor errado com confiança.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from . import glyphs
from .profile import Profile

GLYPH_FIELDS = ("hp", "coords", "exp", "hunting_time")


def _patch(h: int, w: int, kind: str, rng: np.random.Generator) -> np.ndarray:
    base = (40, 38, 34) if kind == "escura" else (190, 200, 205)
    p = np.empty((h, w, 3), np.int16)
    p[:] = base
    p += rng.integers(-12, 12, (h, w, 3), dtype=np.int16)
    p[0, :] = p[-1, :] = p[:, 0] = p[:, -1] = (90, 120, 150)  # borda de janela
    return np.clip(p, 0, 255).astype(np.uint8)


def cases(
    image: np.ndarray, profile: Profile, expected: dict, seed: int = 0
) -> Iterator[tuple[str, str, np.ndarray]]:
    """Gera (descrição, campo, imagem coberta)."""
    rng = np.random.default_rng(seed)
    for name in GLYPH_FIELDS:
        want = expected.get(name)
        roi = profile.rois.get(name)
        if not want or want == "?" or roi is None:
            continue
        crop = roi.crop(image)
        box = glyphs.text_extent(glyphs.ink(crop))
        if box is None:
            continue
        x0, _, x1, _ = box
        mid = roi.x + (x0 + x1) // 2
        spans = {
            "inteiro": (roi.x - 2, roi.x + roi.w + 2),
            "metade direita": (mid, roi.x + roi.w + 2),
            "metade esquerda": (roi.x - 2, mid),
        }
        for kind in ("escura", "clara"):
            for label, (a, b) in spans.items():
                img = image.copy()
                y0, y1 = max(0, roi.y - 2), min(img.shape[0], roi.y + roi.h + 2)
                a, b = max(0, a), min(img.shape[1], b)
                img[y0:y1, a:b] = _patch(y1 - y0, b - a, kind, rng)
                yield f"{name} coberto ({label}, janela {kind})", name, img
