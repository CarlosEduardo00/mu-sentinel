"""Leitura por template com texto sintético (sem depender de prints do jogo)."""

import cv2
import numpy as np
import pytest

from musentinel.core.perception import glyphs as G


def render(text: str, bg: tuple[int, int, int] = (20, 20, 160), seed: int = 0) -> np.ndarray:
    """Texto branco sobre fundo colorido com ruído, parecido com o HUD."""
    rng = np.random.default_rng(seed)
    img = np.zeros((22, 12 + 11 * len(text), 3), np.uint8)
    img[:] = bg
    img = np.clip(img.astype(int) + rng.integers(-15, 15, img.shape), 0, 255).astype(np.uint8)
    cv2.putText(img, text, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235, 235, 235), 1, cv2.LINE_AA)
    return img


@pytest.fixture
def font() -> G.GlyphFont:
    f = G.GlyphFont()
    for i, t in enumerate(["0123/4567", "89/105", "6,7:8", "4321/9876"]):
        assert G.learn(f, render(t, seed=i), t)
    return f


@pytest.mark.parametrize("text", ["805/811", "212,32", "1140017/1837420", "00:45:03", "0/811"])
def test_reads_unseen_combinations(font, text):
    got, conf = G.read_text(render(text, seed=99), font)
    assert got == text
    assert conf >= 0.85


def test_background_color_does_not_matter(font):
    for bg in [(20, 160, 20), (160, 20, 20), (40, 40, 40)]:
        got, _ = G.read_text(render("4096/4100", bg=bg, seed=5), font)
        assert got == "4096/4100"


def test_unknown_digit_is_not_silently_dropped():
    f = G.GlyphFont()
    G.learn(f, render("0123456/", seed=1), "0123456/")  # sem 7, 8 e 9
    _, conf = G.read_text(render("789/123", seed=2), f)
    assert conf < 0.85  # leitura não pode sair confiante com dígito faltando


def test_blank_roi_reads_nothing(font):
    img = np.full((22, 80, 3), 30, np.uint8)
    assert G.read_text(img, font) == ("", 0.0)


def test_font_roundtrip(font):
    f2 = G.GlyphFont.from_dict(font.to_dict())
    assert f2.chars() == font.chars()
    assert G.read_text(render("1234", seed=7), f2)[0] == "1234"


def test_ink_suppresses_saturated_colors():
    px = np.array([[[30, 230, 120], [220, 220, 220]]], np.uint8)  # verde vivo, branco
    ink = G.ink(px)
    assert ink[0, 0] < 60 and ink[0, 1] > 200
