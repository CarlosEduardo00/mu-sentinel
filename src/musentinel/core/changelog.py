"""Novidades de cada versão, lidas do CHANGELOG.md que vai junto com o app."""

from __future__ import annotations

import re
from pathlib import Path

from . import paths

_HEAD = re.compile(r"^## \[(\d+(?:\.\d+)*)\](.*)$", re.M)


def _key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def is_newer(a: str, b: str) -> bool:
    """a é mais nova que b? ('0.10.0' > '0.9.1')."""
    return _key(a) > _key(b)


def changelog_path() -> Path:
    for base in (paths.resource_dir(), paths.app_dir(), Path(__file__).resolve().parents[3]):
        p = base / "CHANGELOG.md"
        if p.exists():
            return p
    return paths.resource_dir() / "CHANGELOG.md"


def sections(text: str) -> list[tuple[str, str]]:
    """[(versão, texto da seção)] na ordem do arquivo (mais nova primeiro)."""
    heads = list(_HEAD.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((m.group(1), text[m.start():end].strip()))
    return out


def notes_since(last_seen: str, current: str, text: str | None = None) -> str:
    """Markdown com as seções mais novas que last_seen até a versão atual (vazio = nada novo).

    last_seen vazio (primeira vez com esta função): só a seção da versão atual.
    """
    if text is None:
        p = changelog_path()
        text = p.read_text(encoding="utf-8") if p.exists() else ""
    picked = [body for v, body in sections(text)
              if not is_newer(v, current) and (is_newer(v, last_seen) if last_seen else v == current)]
    return "\n\n".join(picked)
