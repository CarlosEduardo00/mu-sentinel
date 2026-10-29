"""Perfil de calibração por resolução: regiões (ROIs), fontes aprendidas e imagens de referência.

O perfil é um .json que pode ser exportado/importado entre colegas com a mesma
resolução. Não contém nenhum segredo.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, Field, PrivateAttr

from .glyphs import GlyphFont

SCHEMA_VERSION = 1


class Roi(BaseModel):
    x: int
    y: int
    w: int
    h: int

    def crop(self, img: np.ndarray) -> np.ndarray:
        return img[self.y : self.y + self.h, self.x : self.x + self.w]

    def fits(self, size: tuple[int, int]) -> bool:
        w, h = size
        return self.x >= 0 and self.y >= 0 and self.x + self.w <= w and self.y + self.h <= h


# Campos lidos do HUD. "glyph" = dígitos por template; "ocr" = texto livre;
# "ref" = só checa se a região bate com uma imagem de referência (painel aberto?).
FIELD_KINDS: dict[str, str] = {
    "hp": "glyph",
    "coords": "glyph",
    "exp": "glyph",
    "hunting_time": "glyph",
    "map": "ocr",
    "messages": "ocr",
    "hunting_log_title": "ref",
}

FIELD_LABELS_PT: dict[str, str] = {
    "hp": "HP (orbe vermelho)",
    "coords": "Coordenadas",
    "exp": "EXP (barra inferior)",
    "hunting_time": "Hunting Time",
    "map": "Nome do mapa",
    "messages": "Mensagens do sistema",
    "hunting_log_title": "Título do Instant Hunting Log",
}

CHARSETS: dict[str, str] = {
    "hp": "0123456789/",
    "coords": "0123456789,",
    "exp": "0123456789/",
    "hunting_time": "0123456789:",
}


class Profile(BaseModel):
    schema_version: int = SCHEMA_VERSION
    name: str
    client_size: tuple[int, int]
    rois: dict[str, Roi] = Field(default_factory=dict)
    fonts: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    refs: dict[str, str] = Field(default_factory=dict)  # campo -> PNG base64
    notes: str = ""
    updated_at: str = ""

    _font_cache: dict[str, GlyphFont] = PrivateAttr(default_factory=dict)

    # ------------------------------------------------------------ fontes
    def font(self, field: str) -> GlyphFont:
        f = self._font_cache.get(field)
        if f is None:
            f = GlyphFont.from_dict(self.fonts.get(field, {}))
            self._font_cache[field] = f
        return f

    def store_font(self, field: str, font: GlyphFont) -> None:
        self._font_cache[field] = font
        self.fonts[field] = font.to_dict()

    def reading_font(self, field: str) -> GlyphFont:
        """Fonte do campo + caracteres que ele ainda não conhece, emprestados de outros campos
        (mesma fonte do HUD, mas com pequenas diferenças de escala: pontuam um pouco menos)."""
        own = self.font(field)
        missing = set(CHARSETS.get(field, "")) - own.chars()
        if not missing:
            return own
        merged = GlyphFont(glyphs=dict(own.glyphs))
        for other in CHARSETS:
            if other == field:
                continue
            of = self.font(other)
            for c in list(missing):
                if of.glyphs.get(c):
                    merged.glyphs[c] = list(of.glyphs[c])
                    missing.discard(c)
        return merged

    def missing_chars(self, field: str) -> set[str]:
        cs = CHARSETS.get(field, "")
        return set(cs) - self.font(field).chars()

    # ------------------------------------------------------------ referências
    def ref_image(self, field: str) -> np.ndarray | None:
        data = self.refs.get(field)
        if not data:
            return None
        arr = np.frombuffer(base64.b64decode(data), np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def set_ref_image(self, field: str, img: np.ndarray) -> None:
        ok, png = cv2.imencode(".png", img)
        assert ok
        self.refs[field] = base64.b64encode(png.tobytes()).decode()

    # ------------------------------------------------------------ mapas
    def map_refs(self) -> dict[str, np.ndarray]:
        """Imagens (tinta, aparadas) do nome de cada mapa já rotulado."""
        out = {}
        for k in self.refs:
            if k.startswith("map:"):
                img = self.ref_image(k)
                if img is not None:
                    out[k[4:]] = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return out

    def learn_map(self, name: str, crop_bgr: np.ndarray) -> bool:
        from .glyphs import ink, text_extent

        im = ink(crop_bgr)
        box = text_extent(im)
        if box is None:
            return False
        x0, y0, x1, y1 = box
        piece = im[max(0, y0 - 1) : y1 + 1, max(0, x0 - 1) : x1 + 1]
        self.set_ref_image(f"map:{name}", cv2.cvtColor(piece, cv2.COLOR_GRAY2BGR))
        return True

    # ------------------------------------------------------------ arquivo
    def save(self, path: Path) -> None:
        for k, f in self._font_cache.items():
            self.fonts[k] = f.to_dict()
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(self.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Profile:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(migrate(data))


def migrate(data: dict) -> dict:
    """Converte perfis de versões antigas. Hoje só existe a versão 1."""
    v = data.get("schema_version", 1)
    if v > SCHEMA_VERSION:
        raise ValueError(f"perfil de versão {v} é mais novo que este app (suporta {SCHEMA_VERSION})")
    return data


def default_profile_1280x960() -> Profile:
    """ROIs medidas em prints reais de 1280x960 (jogo em 800x600 com escala do Windows)."""
    return Profile(
        name="1280x960",
        client_size=(1280, 960),
        rois={
            "map": Roi(x=90, y=6, w=100, h=24),
            "coords": Roi(x=188, y=6, w=68, h=24),
            "hp": Roi(x=278, y=880, w=74, h=23),
            "exp": Roi(x=530, y=941, w=210, h=19),
            "hunting_time": Roi(x=1180, y=582, w=84, h=22),
            "hunting_log_title": Roi(x=1040, y=536, w=160, h=20),
            "messages": Roi(x=60, y=690, w=360, h=75),
        },
    )
