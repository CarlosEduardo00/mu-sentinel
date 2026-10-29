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


# regiões que a suíte usa (mensagens do sistema ficam de fora: grandes e sem teste)
TESTED_ROIS = ("hp", "coords", "exp", "hunting_time", "map", "hunting_log_title")


def mask_to_rois(img: np.ndarray, rois, pad: int = 6) -> np.ndarray:
    """Mantém só as regiões do HUD (com folga) e apaga o resto.

    Os testes só leem essas regiões; o resto preto comprime quase a zero e a
    suíte cabe no git (1280x960 inteiro = ~2 MB por print; mascarado = poucos KB).
    """
    out = np.zeros_like(img)
    h, w = img.shape[:2]
    for r in rois:
        y0, y1 = max(0, r.y - pad), min(h, r.y + r.h + pad)
        x0, x1 = max(0, r.x - pad), min(w, r.x + r.w + pad)
        out[y0:y1, x0:x1] = img[y0:y1, x0:x1]
    return out


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
