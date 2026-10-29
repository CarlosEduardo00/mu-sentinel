"""Ponto de entrada. Na Fase 0 abre a tela de calibração."""

from __future__ import annotations

import sys


def main() -> int:
    from .gui.calibration import main as calibration_main

    return calibration_main()


if __name__ == "__main__":
    sys.exit(main())
