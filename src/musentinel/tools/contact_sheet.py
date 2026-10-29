"""Folha-resumo dos gabaritos: recorte de cada campo com o valor rotulado ao lado.

Uso: python -m musentinel.tools.contact_sheet
Gera reports/folha_NN.png (25 prints por página). Uma olhada confere tudo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from ..core import paths
from ..core.perception.dataset import load_all

FIELDS = ("hp", "coords", "exp", "hunting_time", "map")
PER_PAGE = 25


def row(img: np.ndarray, expected: dict, profile, name: str) -> np.ndarray:
    cells = []
    for f in FIELDS:
        roi = profile.rois[f]
        c = cv2.resize(roi.crop(img), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        cell = np.full((70, max(c.shape[1], 170), 3), 25, np.uint8)
        cell[: c.shape[0], : c.shape[1]] = c
        v = expected.get(f, "—")
        txt = "(ausente)" if v is None else str(v)
        cv2.putText(cell, txt, (4, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
        cells.append(cell)
    r = np.hstack(cells)
    head = np.full((18, r.shape[1], 3), 50, np.uint8)
    cv2.putText(head, name, (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1, cv2.LINE_AA)
    return np.vstack([head, r, np.full((4, r.shape[1], 3), 90, np.uint8)])


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Folha-resumo dos gabaritos.")
    ap.add_argument("--tamanho", default="1280x960")
    size = paths.parse_size(ap.parse_args(argv).tamanho)
    samples = load_all(paths.fixtures_dir(size))
    if not samples:
        print("Suíte vazia.")
        return 1
    profile = paths.load_or_default_profile(*size)
    out_dir = paths.app_dir() / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = 0
    for p0 in range(0, len(samples), PER_PAGE):
        rows = []
        for s in samples[p0 : p0 + PER_PAGE]:
            img = s.image()
            if img.shape[1::-1] != tuple(profile.client_size):
                continue
            rows.append(row(img, s.expected, profile, f"{s.scene}/{s.png.name}"))
        if not rows:
            continue
        w = max(r.shape[1] for r in rows)
        sheet = np.vstack([np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0))) for r in rows])
        pages += 1
        out: Path = out_dir / f"folha_{pages:02d}.png"
        cv2.imencode(".png", sheet)[1].tofile(str(out))
    print(f"{pages} página(s) em {out_dir} ({len(samples)} prints)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
