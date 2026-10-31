"""Número maior que a área de leitura (HP passou de 999, EXP ganhou um dígito): nunca lê pela metade.

Antes: HP 1200 numa área feita para "980/980" virava "200" e disparava HP baixo; "211,33" virava "11,33".
"""

import json

import cv2
import numpy as np
import pytest

from musentinel.core import paths
from musentinel.core.perception import glyphs
from musentinel.core.perception.fields import PARSERS
from musentinel.core.perception.profile import CHARSETS, Roi
from musentinel.core.perception.reader import CUT_NOTE, HudReader

# campos com fonte completa nestes tamanhos (o leitor não precisa do OCR de confirmação)
CASES = [((1280, 960), "exp"), ((800, 600), "coords"), ((800, 600), "exp")]


def _samples(size, name, n=6):
    out = []
    for jf in sorted((paths.fixtures_dir(size) / "cacando").glob("*.json")):
        want = json.loads(jf.read_text(encoding="utf-8"))["expected"].get(name)
        if want and want != "?":
            img = cv2.imdecode(np.fromfile(str(jf.with_suffix(".png")), np.uint8), cv2.IMREAD_COLOR)
            out.append((img, want))
        if len(out) >= n:
            break
    return out


def _chars(prof, name, img):
    info = {}
    roi = prof.rois[name]
    text, _, _ = glyphs.read_text_ex(roi.crop(img), prof.reading_font(name), CHARSETS[name], info=info)
    return text, info["chars"]


@pytest.mark.parametrize("size,name", CASES)
@pytest.mark.parametrize("side", ["esquerda", "direita"])
def test_digit_outside_area_is_read_and_area_grows(size, name, side):
    if not paths.seed_profile_path(*size).exists():
        pytest.skip("sem perfil-semente")
    for img, want in _samples(size, name):
        prof = paths.load_or_default_profile(*size)
        text, ch = _chars(prof, name, img)
        assert text == want
        roi = prof.rois[name]
        if side == "esquerda":  # o 1º dígito inteiro fica fora da área
            cut = ch[0][0] + ch[0][1]
            prof.rois[name] = Roi(x=roi.x + cut, y=roi.y, w=roi.w - cut, h=roi.h)
        else:  # o último dígito inteiro fica fora
            prof.rois[name] = Roi(x=roi.x, y=roi.y, w=ch[-1][0], h=roi.h)
        prof.extents[name] = [(5, 60)] * 3
        reader = HudReader(prof, ocr_fallback=False)
        r = reader.read_field(img, name)
        assert r.ok and r.value == PARSERS[name](want, 1.0).value, (want, r.raw)
        assert reader.grown == {name}
        new = prof.rois[name]
        if side == "esquerda":
            shift = (roi.x + cut) - new.x
            assert shift > 0 and prof.extents[name][0] == (5 + shift, 60 + shift)  # posições acompanham a área
        again = HudReader(prof, ocr_fallback=False)
        assert again.read_field(img, name).value == r.value and not again.grown  # a área nova já basta


def test_number_still_cut_at_max_growth_is_unreadable():
    size, name = (1280, 960), "exp"
    img, want = _samples(size, name, 1)[0]
    prof = paths.load_or_default_profile(*size)
    _, ch = _chars(prof, name, img)
    roi = prof.rois[name]
    # área de 3 caracteres no meio do número: mesmo ampliando 3 vezes de cada lado não cabe tudo
    assert len(ch) >= 12, want
    x0, x1 = ch[4][0], ch[6][0] + ch[6][1]
    prof.rois[name] = Roi(x=roi.x + x0, y=roi.y, w=x1 - x0, h=roi.h)
    r = HudReader(prof, ocr_fallback=False).read_field(img, name)
    assert not r.ok and CUT_NOTE in r.raw, r.raw


def test_normal_reads_do_not_grow():
    for size, name in CASES:
        prof = paths.load_or_default_profile(*size)
        reader = HudReader(prof, ocr_fallback=False)
        before = prof.rois[name]
        for img, want in _samples(size, name):
            assert reader.read_field(img, name).value == PARSERS[name](want, 1.0).value
        assert not reader.grown and prof.rois[name] == before


def test_attached_rejects_loose_marks():
    span = (20, 60)
    assert glyphs.attached([(13, 6, "1"), (20, 40, "x")], span, 4)  # colado (1 px)
    assert glyphs.attached([(5, 6, "1"), (13, 6, "2"), (20, 40, "x")], span, 4)  # dois em sequência
    assert not glyphs.attached([(2, 6, "5"), (20, 40, "x")], span, 4)  # solto a 12 px: arte do orbe
    assert not glyphs.attached([(20, 40, "x"), (70, 6, "8")], span, 4)  # solto à direita
    assert glyphs.attached([(20, 40, "x"), (62, 6, "0")], span, 4)
    assert glyphs.attached([(20, 40, "1"), (69, 5, "/")], span, 4)  # "/" do EXP com espaço em volta
    assert not glyphs.attached([(20, 40, "1"), (69, 6, "8")], span, 4)
