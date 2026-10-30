"""Calibração automática do HUD com o OCR completo da tela (prints reais 1280x960)."""

from pathlib import Path

import cv2
import pytest

from musentinel.core.perception import autocal
from musentinel.core.perception import panels as P
from musentinel.core.perception.ocr import OcrEngine
from musentinel.core.perception.profile import Profile, default_profile_1280x960
from musentinel.core.perception.reader import HudReader

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "panels_800x600"


@pytest.fixture(scope="module")
def ocr():
    return OcrEngine()


@pytest.fixture(scope="module")
def pipe(ocr):
    img = cv2.imread(str(FIX / "c_i_cacada_1280.png"))
    hits, boxes = P.scan(img, ocr)
    return img, hits, boxes


def test_new_resolution_from_scratch(pipe, ocr):
    """Tamanho sem perfil nenhum: um print basta para criar as regiões e ensinar os dígitos."""
    img, hits, boxes = pipe
    prof = Profile(name="1280x960", client_size=(1280, 960))
    prof, res = autocal.calibrate(img, ocr, prof, boxes=boxes, caca=hits["caca"])
    assert res.found == {"map": "Kanturu", "coords": "140,45", "hp": "1186/1189", "exp": "3947230/5412200",
                         "hunting_time": "00:27:46"}
    assert set(res.moved) >= {"map", "coords", "hp", "exp", "hunting_time"}
    fast = HudReader(prof, ocr=ocr, ocr_fallback=False).read(img)  # só o leitor rápido
    # um print não tem todos os dígitos: o leitor rápido já lê certo, mas pede confirmação do OCR
    assert fast.get("hp").raw == "1186/1189" and fast.get("exp").raw == "3947230/5412200"
    r = HudReader(prof, ocr=ocr).read(img)
    assert r.value("hp") == (1186, 1189) and r.value("exp") == (3947230, 5412200)
    assert r.value("coords") == (140, 45) and r.value("map") == "Kanturu"
    ht = HudReader(prof, ocr=ocr).read_field_at(img, "hunting_time", autocal.hunting_time_roi(hits["caca"], (1280, 960)))
    assert ht.value == 27 * 60 + 46


def test_existing_profile_learns_what_it_misses(ocr):
    """Loja: o perfil de fábrica errava as coordenadas (46,225) e o HP (08/28)."""
    img = cv2.imread(str(FIX / "loja_gremory_1280.png"))
    prof = default_profile_1280x960()
    prof, res = autocal.calibrate(img, ocr, prof)
    assert res.found["coords"] == "48,225" and res.found["map"] == "Elbeland" and res.found["hp"] == "208/208"
    r = HudReader(prof, ocr=ocr).read(img)
    assert r.value("coords") == (48, 225) and r.value("hp") == (208, 208)


def test_wrong_size_is_refused(pipe, ocr):
    img, _, boxes = pipe
    with pytest.raises(ValueError):
        autocal.calibrate(img, ocr, Profile(name="800x600", client_size=(800, 600)), boxes=boxes)


def test_nothing_found_learns_nothing(ocr):
    img = cv2.imread(str(FIX / "c_i_cacada_1280.png"))
    img[:] = 20  # tela escura (loading): não inventa valores
    prof = default_profile_1280x960()
    before = prof.model_dump()
    prof, res = autocal.calibrate(img, ocr, prof)
    assert not res.found and not res.learned and not res.moved and prof.model_dump() == before


def test_anchor_tolerance_grows_with_text_width():
    p = Profile(name="t", client_size=(10, 10))
    p.extents["exp"] = [(35, 173), (60, 157), (40, 170), (55, 160), (45, 166)]
    side, pos, tol = p.anchor("exp")
    assert side == "center" and tol >= 7  # EXP 81186/1316440 (centro 5 px fora) não é mais recusado
