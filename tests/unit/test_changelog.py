"""Versão única e novidades por versão (CHANGELOG.md)."""

import re
from pathlib import Path

import musentinel
from musentinel.core import changelog
from musentinel.core.config import Config

ROOT = Path(__file__).resolve().parents[2]

TEXT = """# Novidades

## [0.3.0] - 2026-11-10
- terceira

## [0.2.0] - 2026-10-30
- segunda

## [0.1.0] - 2026-10-29
- primeira
"""


def test_version_comes_from_single_place():
    src = (ROOT / "src" / "musentinel" / "_version.py").read_text(encoding="utf-8")
    assert musentinel.__version__ == re.search(r'__version__ = "([^"]+)"', src).group(1)
    assert 'dynamic = ["version"]' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_changelog_has_current_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.sections(text)[0][0] == musentinel.__version__  # não esquecer as novidades no lançamento


def test_notes_since_last_seen():
    assert "segunda" in changelog.notes_since("", "0.2.0", TEXT) and "primeira" not in changelog.notes_since("", "0.2.0", TEXT)
    n = changelog.notes_since("0.1.0", "0.3.0", TEXT)
    assert "terceira" in n and "segunda" in n and "primeira" not in n
    assert changelog.notes_since("0.3.0", "0.3.0", TEXT) == ""
    assert changelog.is_newer("0.10.0", "0.9.1") and not changelog.is_newer("0.2.0", "0.2.0")


def test_config_remembers_seen_version():
    c = Config()
    c.last_seen_version = "0.2.0"
    assert "novidades_vistas_ate: 0.2.0" in c.to_yaml()
    assert Config.from_yaml(c.to_yaml()).last_seen_version == "0.2.0"
