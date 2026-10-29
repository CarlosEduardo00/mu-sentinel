"""Relatório de acurácia da percepção sobre a suíte de prints rotulados.

Uso:
    python -m musentinel.tools.accuracy_report
    python -m musentinel.tools.accuracy_report --modo perfil   # usa o perfil calibrado salvo

Modo padrão "holdout": parte do zero (só as ROIs do perfil), aprende com 1 a
cada 5 prints e mede nos outros 4. Assim a nota não é inflada por medir nos
mesmos prints usados para aprender.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..core import paths
from ..core.perception.dataset import Sample, judge, load_all
from ..core.perception.profile import Profile
from ..core.perception.reader import HudReader
from ..core.perception.training import train

FIELDS = ("hp", "coords", "exp", "hunting_time", "map")
TARGET = 0.98


def evaluate(profile: Profile, samples: list[Sample]) -> dict:
    reader = HudReader(profile)
    per_field = defaultdict(lambda: [0, 0, 0])  # acertos, total, erros confiantes
    per_scene = defaultdict(lambda: [0, 0])
    errors: list[str] = []
    times: list[float] = []
    for s in samples:
        img = s.image()
        fields = tuple(f for f in FIELDS if f in s.expected)
        t = time.perf_counter()
        hud = reader.read(img, fields)
        times.append((time.perf_counter() - t) * 1000)
        for f in fields:
            ok, confident_wrong = judge(f, s.expected[f], hud.fields[f])
            pf = per_field[f]
            pf[0] += ok
            pf[1] += 1
            pf[2] += confident_wrong
            per_scene[s.scene][0] += ok
            per_scene[s.scene][1] += 1
            if not ok:
                g = hud.fields[f]
                errors.append(
                    f"{s.png.parent.name}/{s.png.name} · {f}: esperado {s.expected[f]!r}, "
                    f"lido {g.raw!r} ({g.status}, conf {g.confidence:.2f})"
                    + ("  ← ERRO CONFIANTE" if confident_wrong else "")
                )
    hits = sum(v[0] for v in per_field.values())
    total = sum(v[1] for v in per_field.values())
    return {
        "per_field": dict(per_field),
        "per_scene": dict(per_scene),
        "errors": errors,
        "accuracy": hits / total if total else 0.0,
        "hits": hits,
        "total": total,
        "confident_wrong": sum(v[2] for v in per_field.values()),
        "ms_median": sorted(times)[len(times) // 2] if times else 0.0,
    }


def render(res: dict, n_samples: int, mode: str, n_train: int) -> str:
    acc = res["accuracy"]
    lines = [
        "# Relatório de acurácia da percepção",
        "",
        f"- Data: {datetime.now():%d/%m/%Y %H:%M}",
        f"- Modo: {mode}" + (f" (aprendeu com {n_train} prints, mediu em {n_samples})" if mode == "holdout" else ""),
        f"- Prints avaliados: {n_samples}",
        f"- **Acerto geral: {acc:.2%}** ({res['hits']}/{res['total']} campos) — meta {TARGET:.0%}: "
        + ("**ATINGIDA**" if acc >= TARGET else "**NÃO atingida**"),
        f"- Erros confiantes (valor errado afirmado com confiança): {res['confident_wrong']}",
        f"- Tempo mediano de leitura por print: {res['ms_median']:.0f} ms",
        "",
        "## Por campo",
        "",
        "| Campo | Acertos | Total | % | Erros confiantes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for f in FIELDS:
        if f in res["per_field"]:
            h, t, c = res["per_field"][f]
            lines.append(f"| {f} | {h} | {t} | {h / t:.1%} | {c} |")
    lines += ["", "## Por cena", "", "| Cena | Acertos | Total | % |", "| --- | --- | --- | --- |"]
    for sc, (h, t) in sorted(res["per_scene"].items()):
        lines.append(f"| {sc} | {h} | {t} | {h / t:.1%} |")
    if res["errors"]:
        lines += ["", f"## Erros ({len(res['errors'])})", ""]
        lines += [f"- {e}" for e in res["errors"][:300]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mede a acurácia da leitura do HUD.")
    ap.add_argument("--suite", type=Path, default=paths.fixtures_dir())
    ap.add_argument("--modo", choices=["holdout", "perfil"], default="holdout")
    ap.add_argument("--perfil", type=Path, default=None, help="perfil .json (padrão: o salvo 1280x960)")
    ap.add_argument("--saida", type=Path, default=paths.app_dir() / "reports")
    a = ap.parse_args(argv)

    samples = load_all(a.suite)
    if not samples:
        print(f"Nenhum print rotulado em {a.suite}")
        return 1
    base = Profile.load(a.perfil) if a.perfil else paths.load_or_default_profile()

    if a.modo == "holdout":
        train_set = samples[::5]
        test_set = [s for i, s in enumerate(samples) if i % 5]
        prof = Profile(name=base.name, client_size=base.client_size, rois=base.rois)
        train(prof, train_set)
    else:
        train_set, test_set, prof = [], samples, base

    res = evaluate(prof, test_set)
    text = render(res, len(test_set), a.modo, len(train_set))
    a.saida.mkdir(parents=True, exist_ok=True)
    out = a.saida / f"acuracia_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Relatório salvo em {out}")
    return 0 if res["accuracy"] >= TARGET else 2


if __name__ == "__main__":
    sys.exit(main())
