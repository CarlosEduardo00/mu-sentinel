"""Gera o perfil-semente que vai junto com o app (assets/profiles/1280x960.json),
treinado com toda a suíte de prints rotulados.

Uso: python -m musentinel.tools.seed_profile
"""

from __future__ import annotations

import sys

from ..core import paths
from ..core.perception.dataset import load_all
from ..core.perception.profile import default_profile_1280x960
from ..core.perception.training import train


def main() -> int:
    samples = [s for s in load_all(paths.fixtures_dir()) if s.image().shape[1::-1] == (1280, 960)]
    if not samples:
        print("Suíte vazia.")
        return 1
    # Mesmo esquema do relatório "holdout": aprende com 1 a cada 5 prints. Treinar com
    # todos acumula variantes ruins e PIORA a leitura; assim a acurácia medida nos
    # outros 4/5 vale para este perfil.
    prof = train(default_profile_1280x960(), samples[::5])
    out = paths.app_dir() / "assets" / "profiles" / "1280x960.json"
    prof.save(out)
    missing = {f: "".join(sorted(prof.missing_chars(f))) for f in ("hp", "coords", "exp", "hunting_time")}
    print(f"Perfil-semente salvo em {out} ({len(samples)} prints). Faltando: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
