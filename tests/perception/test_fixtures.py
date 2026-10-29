"""Percepção sobre os prints reais rotulados (uma suíte por resolução):
tests/fixtures/screens/ (1280x960) e tests/fixtures/screens_<L>x<A>/.

- Erro confiante (valor errado afirmado) nunca é aceito.
- A meta de 98% só é cobrada quando a suíte tiver pelo menos 200 prints
  (aceite da Fase 0). Antes disso o teste é pulado com a contagem atual.
"""

import pytest

from musentinel.core import paths
from musentinel.core.perception.dataset import load_all
from musentinel.core.perception.profile import Profile
from musentinel.core.perception.training import train
from musentinel.tools.accuracy_report import evaluate

SIZES = [(1280, 960), (800, 600)]
SUITES = {size: load_all(paths.fixtures_dir(size)) for size in SIZES}
MIN_SUITE = 200
ids = [f"{w}x{h}" for w, h in SIZES]


def holdout_profile(size) -> tuple[Profile, list]:
    samples = SUITES[size]
    base = paths.load_or_default_profile(*size)
    prof = Profile(name=base.name, client_size=base.client_size, rois=base.rois)
    train(prof, samples[::5])
    return prof, [s for i, s in enumerate(samples) if i % 5]


@pytest.mark.parametrize("size", SIZES, ids=ids)
def test_seed_profile_reads_all_fixtures(size):
    """Regressão: o perfil-semente (treinado com a suíte) lê toda a suíte."""
    if not SUITES[size] or not paths.seed_profile_path(*size).exists():
        pytest.skip("sem suíte ou sem perfil-semente")
    res = evaluate(paths.load_or_default_profile(*size), SUITES[size])
    assert res["confident_wrong"] == 0, res["errors"]
    assert res["accuracy"] >= 0.98, res["errors"]


@pytest.mark.parametrize("size", SIZES, ids=ids)
def test_holdout_never_confidently_wrong(size):
    if len(SUITES[size]) < 10:
        pytest.skip("suíte pequena demais para holdout")
    prof, test_set = holdout_profile(size)
    res = evaluate(prof, test_set)
    assert res["confident_wrong"] == 0, res["errors"]


@pytest.mark.parametrize("size", SIZES, ids=ids)
def test_holdout_accuracy_meets_target(size):
    if len(SUITES[size]) < MIN_SUITE:
        pytest.skip(f"suíte com {len(SUITES[size])} prints; a meta exige {MIN_SUITE}")
    prof, test_set = holdout_profile(size)
    res = evaluate(prof, test_set)
    assert res["accuracy"] >= 0.98, res["errors"][:30]
