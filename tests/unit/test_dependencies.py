"""Todo pacote de terceiros importado pelo app precisa estar declarado no pyproject.toml.

O build roda num ambiente limpo que instala só o que está declarado; um import esquecido
(mesmo dentro de função) some do executável e só quebra no PC do usuário.
"""

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "musentinel"


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared() -> set[str]:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    return {_norm(re.split(r"[<>=!~;\[ ]", d, maxsplit=1)[0]) for d in deps}


def _imported_top_levels() -> dict[str, str]:
    found: dict[str, str] = {}
    for py in SRC.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for n in names:
                found.setdefault(n.split(".")[0], py.relative_to(ROOT).as_posix())
    return found


def test_third_party_imports_are_declared():
    declared = _declared()
    dists = packages_distributions()
    missing = []
    for top, where in sorted(_imported_top_levels().items()):
        if top in sys.stdlib_module_names or top == "musentinel":
            continue
        owners = {_norm(d) for d in dists.get(top, [])}
        if not owners & declared:
            missing.append(f"{top} ({where}; pacote: {', '.join(sorted(owners)) or '?'})")
    assert not missing, "imports sem dependência declarada no pyproject.toml: " + "; ".join(missing)
