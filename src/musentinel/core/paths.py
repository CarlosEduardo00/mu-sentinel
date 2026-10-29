"""Pastas de dados do app (%APPDATA%\\MUSentinel ou modo portátil)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "MUSentinel"


def app_dir() -> Path:
    """Pasta do executável (empacotado) ou raiz do projeto (código-fonte)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    """Modo portátil se existir portable.flag ao lado do .exe; senão %APPDATA%."""
    if (app_dir() / "portable.flag").exists():
        d = app_dir() / "data"
    else:
        d = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def profiles_dir() -> Path:
    d = data_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def captures_dir() -> Path:
    d = data_dir() / "captures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fixtures_dir() -> Path:
    """Suíte de prints rotulados (só existe rodando do código-fonte)."""
    return app_dir() / "tests" / "fixtures" / "screens"


def profile_path(width: int, height: int) -> Path:
    return profiles_dir() / f"{width}x{height}.json"


def load_or_default_profile(width: int = 1280, height: int = 960):
    from .perception.profile import Profile, default_profile_1280x960

    p = profile_path(width, height)
    if p.exists():
        return Profile.load(p)
    seed = app_dir() / "assets" / "profiles" / f"{width}x{height}.json"
    if seed.exists():  # perfil-semente que vem com o app
        return Profile.load(seed)
    if (width, height) == (1280, 960):
        return default_profile_1280x960()
    return Profile(name=f"{width}x{height}", client_size=(width, height))
