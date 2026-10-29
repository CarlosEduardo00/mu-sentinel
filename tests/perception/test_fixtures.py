"""Percepção sobre os prints reais rotulados em tests/fixtures/screens/.

- Erro confiante (valor errado afirmado) nunca é aceito.
- A meta de 98% só é cobrada quando a suíte tiver pelo menos 200 prints
  (aceite da Fase 0). Antes disso o teste é pulado com a contagem atual.
"""

import pytest

from musentinel.core import paths
from musentinel.core.perception.dataset import load_all
from musentinel.core.perception.profile import Profile
from musentinel.tools.accuracy_report import evaluate
from musentinel.core.perception.training import train

SAMPLES = load_all(paths.fixtures_dir())
MIN_SUITE = 200


def holdout_profile() -> tuple[Profile, list]:
    base = paths.load_or_default_profile()
    prof = Profile(name=base.name, client_size=base.client_size, rois=base.rois)
    train(prof, SAMPLES[::5])
    return prof, [s for i, s in enumerate(SAMPLES) if i % 5]


@pytest.mark.skipif(not SAMPLES, reason="suíte de prints vazia")
def test_seed_profile_reads_all_fixtures():
    """Regressão: o perfil-semente (treinado com a suíte) lê toda a suíte."""
    res = evaluate(paths.load_or_default_profile(), SAMPLES)
    assert res["confident_wrong"] == 0, res["errors"]
    assert res["accuracy"] >= 0.98, res["errors"]


@pytest.mark.skipif(len(SAMPLES) < 10, reason="suíte pequena demais para holdout")
def test_holdout_never_confidently_wrong():
    prof, test_set = holdout_profile()
    res = evaluate(prof, test_set)
    assert res["confident_wrong"] == 0, res["errors"]


@pytest.mark.skipif(len(SAMPLES) < MIN_SUITE, reason=f"suíte com {len(SAMPLES)} prints; a meta exige {MIN_SUITE}")
def test_holdout_accuracy_meets_target():
    prof, test_set = holdout_profile()
    res = evaluate(prof, test_set)
    assert res["accuracy"] >= 0.98, res["errors"][:30]
