"""HUD coberto por menus/janelas: o leitor nunca pode afirmar um valor errado."""

import pytest

from musentinel.core import paths
from musentinel.core.perception.dataset import judge, load_all
from musentinel.core.perception.occlusion import cases
from musentinel.core.perception.reader import HudReader

SAMPLES = load_all(paths.fixtures_dir())[::4]  # um a cada 4 já cobre a variedade


@pytest.mark.skipif(not SAMPLES, reason="suíte de prints vazia")
def test_covered_fields_are_never_confidently_wrong():
    profile = paths.load_or_default_profile()
    reader = HudReader(profile)
    bad = []
    n = 0
    for i, s in enumerate(SAMPLES):
        for desc, name, img in cases(s.image(), profile, s.expected, seed=i):
            n += 1
            got = reader.read_field(img, name)
            if got.ok and not judge(name, s.expected[name], got)[0]:
                bad.append(f"{s.png.name} · {desc}: leu {got.raw!r} (conf {got.confidence:.2f})")
    assert n > 0
    assert not bad, "\n".join(bad)
