"""Gera assets/musentinel.ico (ícone do .exe) e assets/musentinel.png a partir do desenho em gui/icons.py.

Uso: python -m musentinel.tools.make_icon
Rode de novo sempre que mudar o desenho do ícone e faça o commit dos dois arquivos.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 (o QPainter precisa dele)
    from ..core import paths
    from ..gui import icons

    out = paths.app_dir() / "assets"
    ico = out / "musentinel.ico"
    png = out / "musentinel.png"
    ico.write_bytes(icons.ico_bytes())
    icons.draw_brand(256).save(str(png))
    for p in (ico, png):
        print(f"{p}  ({Path(p).stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
