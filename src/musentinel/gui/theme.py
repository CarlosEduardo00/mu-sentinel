"""Aparência do app: ícone, cores e estilo, acompanhando o tema claro ou escuro do Windows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

GREEN = "#2ea043"
AMBER = "#d29b00"
RED = "#e5484d"
BLUE = "#3b82c4"
GRAY = "#8b949e"
LINK = "#4493f8"


def is_dark() -> bool:
    app = QGuiApplication.instance()
    if app is None:
        return False
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt antigo
        return False


def colors() -> dict[str, str]:
    if is_dark():
        return {
            "card": "#2a2a2a", "border": "#3d3d3d", "muted": "#9a9a9a", "track": "#3a3a3a",
            "warn_bg": "#3b2f12", "warn_fg": "#f3d68a", "warn_border": "#6b5317",
            "chip": "#333333", "thumb": "#111111", "link": LINK,
        }
    return {
        "card": "#ffffff", "border": "#d9d9d9", "muted": "#6e6e6e", "track": "#e6e6e6",
        "warn_bg": "#fff4d6", "warn_fg": "#5a4300", "warn_border": "#e6c56a",
        "chip": "#f2f2f2", "thumb": "#111111", "link": "#0b57d0",
    }


def stylesheet() -> str:
    c = colors()
    return f"""
QFrame#card {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#card[alerta="true"] {{ border: 2px solid {RED}; }}
QLabel#cardTitle {{ font-size: 16px; font-weight: 600; }}
QLabel#muted, QLabel#cardSub {{ color: {c['muted']}; }}
QLabel#rowLabel {{ color: {c['muted']}; }}
QLabel#thumb {{ background: {c['thumb']}; color: {c['muted']}; border-radius: 6px; }}
QLabel#banner {{ background: {c['warn_bg']}; color: {c['warn_fg']}; border: 1px solid {c['warn_border']};
                 border-radius: 8px; padding: 8px 10px; }}
QLabel#summary {{ font-size: 14px; font-weight: 600; padding: 0 10px; }}
QLabel#chip {{ background: {c['chip']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 2px 9px; }}
QLabel#emptyTitle {{ font-size: 18px; font-weight: 600; }}
QLabel#emptyText {{ color: {c['muted']}; font-size: 13px; }}
QProgressBar#hp {{ background: {c['track']}; border: none; border-radius: 4px; min-height: 16px; max-height: 16px;
                   text-align: center; font-weight: 600; }}
"""


def apply(app) -> None:
    """Ícone em todas as janelas do app e o estilo do tema atual (refeito se o Windows trocar de tema)."""
    from . import icons

    app.setWindowIcon(icons.app_icon())
    app.setStyleSheet(stylesheet())
    try:
        app.styleHints().colorSchemeChanged.connect(lambda *_: app.setStyleSheet(stylesheet()))
    except AttributeError:
        pass
