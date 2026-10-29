"""Gera o perfil-semente que vai junto com o app (assets/profiles/<tamanho>.json),
treinado com a suíte de prints rotulados daquela resolução.

Uso: python -m musentinel.tools.seed_profile [--tamanho 800x600]
"""

from __future__ import annotations

import argparse
import sys

from ..core import paths
from ..core.perception.dataset import load_all
from ..core.perception.profile import Profile, default_profile
from ..core.perception.training import train


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gera o perfil-semente de uma resolução.")
    ap.add_argument("--tamanho", default="1280x960")
    size = paths.parse_size(ap.parse_args(argv).tamanho)
    samples = [s for s in load_all(paths.fixtures_dir(size)) if s.image().shape[1::-1] == size]
    if not samples:
        print("Suíte vazia.")
        return 1
    # Mesmo esquema do relatório "holdout": aprende com 1 a cada 5 prints. Treinar com
    # todos acumula variantes ruins e PIORA a leitura; assim a acurácia medida nos
    # outros 4/5 vale para este perfil.
    base = default_profile(*size) or paths.load_or_default_profile(*size)
    prof = train(Profile(name=base.name, client_size=base.client_size, rois=base.rois), samples[::5])
    out = paths.seed_profile_path(*size)
    out.parent.mkdir(parents=True, exist_ok=True)
    prof.save(out)
    missing = {f: "".join(sorted(prof.missing_chars(f))) for f in ("hp", "coords", "exp", "hunting_time")}
    print(f"Perfil-semente salvo em {out} ({len(samples)} prints). Faltando: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
