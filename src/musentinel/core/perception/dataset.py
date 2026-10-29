"""Suíte de prints rotulados: tests/fixtures/screens/<cena>/<nome>.png + <nome>.json.

Formato do JSON:
    {
      "scene": "cacando",
      "expected": {
        "hp": "805/811",          # texto exato do HUD
        "coords": "212,32",
        "exp": "1140017/1837420",
        "hunting_time": "00:45:03",   # null = painel fechado
        "map": "Aida"                  # "?" = ilegível (menu por cima etc.)
      }
    }
Campo ausente do "expected" = não avaliado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .fields import PARSERS, FieldReading

SCENES = {
    "cacando": "Caçando",
    "parado": "Parado / Helper desligado",
    "cidade": "Na cidade",
    "morto": "Morto",
    "menu_aberto": "Menu/janela por cima do HUD",
    "loading": "Carregando / troca de mapa",
    "desconectado": "Desconectado",
    "outro": "Outro",
}

UNREADABLE = "?"


@dataclass
class Sample:
    png: Path
    scene: str
    expected: dict[str, str | None] = field(default_factory=dict)

    @property
    def json_path(self) -> Path:
        return self.png.with_suffix(".json")

    def image(self) -> np.ndarray:
        img = cv2.imdecode(np.fromfile(str(self.png), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"não abriu {self.png}")
        return img

    def save(self) -> None:
        self.json_path.write_text(
            json.dumps({"scene": self.scene, "expected": self.expected}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    @staticmethod
    def load(png: Path) -> Sample:
        data = json.loads(png.with_suffix(".json").read_text(encoding="utf-8"))
        return Sample(png, data.get("scene", "outro"), data.get("expected", {}))


def load_all(root: Path) -> list[Sample]:
    if not root.exists():
        return []
    return [Sample.load(p) for p in sorted(root.rglob("*.png")) if p.with_suffix(".json").exists()]


def _norm_expected(name: str, text: str):
    if name in PARSERS:
        r = PARSERS[name](text.replace(" ", ""), 1.0)
        return r.value if r.ok else text
    return text.strip().lower()


def judge(name: str, expected: str | None, got: FieldReading) -> tuple[bool, bool]:
    """Retorna (acertou, erro_confiante).

    Erro confiante = o leitor afirmou um valor (status ok) e ele está errado.
    É o pior tipo de erro: pode virar alerta falso.
    """
    if expected is None or expected == UNREADABLE:
        ok = not got.ok
        return ok, (not ok)
    if not got.ok:
        return False, False
    want = _norm_expected(name, expected)
    have = got.value if name in PARSERS else str(got.value).strip().lower()
    ok = want == have
    return ok, (not ok)
