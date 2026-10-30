"""Ponto de entrada do executável (PyInstaller não aceita import relativo no script)."""

import multiprocessing
import sys

from musentinel.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
