"""Iniciar com o Windows pela chave Run do usuário (HKCU), sem precisar de admin.

Não usa serviço do Windows: serviços rodam na Sessão 0 e não enxergam as janelas do usuário.
"""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "MUSentinel"


def launch_command() -> str:
    """Comando que o Windows roda no login (começa minimizado na bandeja)."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --minimizado'
    exe = Path(sys.executable).resolve()
    pyw = exe.with_name("pythonw.exe")
    return f'"{pyw if pyw.exists() else exe}" -m musentinel --minimizado'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE)
            return True
    except FileNotFoundError:
        return False


def current_command() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return str(winreg.QueryValueEx(k, VALUE)[0])
    except FileNotFoundError:
        return None


def set_enabled(on: bool) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except FileNotFoundError:
                pass
