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


def resource_dir() -> Path:
    """Arquivos que vêm com o app (perfis-semente, ícone). No .exe ficam na pasta _internal."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
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


def fixtures_dir(size: tuple[int, int] = (1280, 960)) -> Path:
    """Suíte de prints rotulados (só existe rodando do código-fonte). Uma pasta por resolução."""
    if tuple(size) == (1280, 960):
        return app_dir() / "tests" / "fixtures" / "screens"
    return app_dir() / "tests" / "fixtures" / f"screens_{size[0]}x{size[1]}"


def parse_size(text: str) -> tuple[int, int]:
    """'800x600' → (800, 600)."""
    w, h = text.lower().split("x")
    return int(w), int(h)


def seed_profile_path(width: int, height: int) -> Path:
    return resource_dir() / "assets" / "profiles" / f"{width}x{height}.json"


def has_profile(width: int, height: int) -> bool:
    """Existe perfil (do usuário, semente ou padrão de fábrica) para esta resolução?"""
    from .perception.profile import DEFAULT_PROFILES

    return (profile_path(width, height).exists() or seed_profile_path(width, height).exists()
            or (width, height) in DEFAULT_PROFILES)


def profile_path(width: int, height: int) -> Path:
    return profiles_dir() / f"{width}x{height}.json"


def load_or_default_profile(width: int = 1280, height: int = 960):
    from .perception.profile import Profile, default_profile

    p = profile_path(width, height)
    if p.exists():
        return Profile.load(p)
    seed = seed_profile_path(width, height)
    if seed.exists():  # perfil-semente que vem com o app
        return Profile.load(seed)
    return default_profile(width, height) or Profile(name=f"{width}x{height}", client_size=(width, height))
