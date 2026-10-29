import numpy as np
import pytest

from musentinel.core.perception.dataset import judge
from musentinel.core.perception.fields import FieldReading, parse_coords, parse_ratio, parse_time
from musentinel.core.perception.ocr import match_name
from musentinel.core.perception.profile import Profile, default_profile_1280x960, migrate


def test_parse_ratio():
    assert parse_ratio("805/811", 0.9).value == (805, 811)
    assert parse_ratio("0/811", 0.9).value == (0, 811)
    assert not parse_ratio("900/811", 0.9).ok  # atual acima do máximo
    assert not parse_ratio("805811", 0.9).ok
    assert not parse_ratio("5/0", 0.9).ok


def test_parse_coords():
    assert parse_coords("212,32", 1).value == (212, 32)
    assert not parse_coords("300,32", 1).ok
    assert not parse_coords("21232", 1).ok


def test_parse_time():
    assert parse_time("00:45:03", 1).value == 45 * 60 + 3
    assert parse_time("12:00:00", 1).value == 12 * 3600
    assert not parse_time("00:75:03", 1).ok


def test_match_map_name_tolerates_ocr_errors():
    maps = ["Aida", "Elbeland", "Kanturu Relics", "Lorencia"]
    assert match_name("Elbeland", maps)[0] == "Elbeland"
    assert match_name("Elbe1and", maps)[0] == "Elbeland"
    assert match_name("KanturuRelics", maps)[0] == "Kanturu Relics"
    assert match_name("xyz", maps)[0] is None


def test_judge():
    ok = FieldReading((805, 811), 0.99, "805/811", "ok")
    bad = FieldReading((805, 817), 0.99, "805/817", "ok")
    unread = FieldReading(None, 0.3, "80", "unreadable")
    assert judge("hp", "805/811", ok) == (True, False)
    assert judge("hp", "805/811", bad) == (False, True)  # erro confiante
    assert judge("hp", "805/811", unread) == (False, False)
    assert judge("hp", "?", unread) == (True, False)
    assert judge("hunting_time", None, unread) == (True, False)
    assert judge("hp", "?", ok) == (False, True)


def test_profile_roundtrip(tmp_path):
    p = default_profile_1280x960()
    p.set_ref_image("hunting_log_title", np.full((20, 160, 3), 200, np.uint8))
    p.learn_map("Aida", np.pad(np.full((10, 30, 3), 220, np.uint8), ((5, 5), (5, 5), (0, 0))))
    f = tmp_path / "p.json"
    p.save(f)
    q = Profile.load(f)
    assert q.rois == p.rois
    assert q.ref_image("hunting_log_title").shape == (20, 160, 3)
    assert "Aida" in q.map_refs()
    assert "senha" not in f.read_text(encoding="utf-8").lower()


def test_profile_from_newer_version_is_rejected():
    with pytest.raises(ValueError):
        migrate({"schema_version": 999})


def test_default_rois_fit_window():
    p = default_profile_1280x960()
    assert all(r.fits((1280, 960)) for r in p.rois.values())
