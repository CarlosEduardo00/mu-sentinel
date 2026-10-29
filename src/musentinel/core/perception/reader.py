"""Leitor do HUD: imagem da janela → valores de cada campo com confiança."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import glyphs
from .fields import PARSERS, FieldReading, absent, unreadable
from .ocr import DEFAULT_MAPS, OcrEngine, match_name
from .profile import CHARSETS, FIELD_KINDS, Profile

DEFAULT_FIELDS = ("hp", "coords", "exp", "hunting_time", "map")


@dataclass
class HudReading:
    fields: dict[str, FieldReading]
    size_ok: bool
    timestamp: float = field(default_factory=time.time)
    elapsed_ms: float = 0.0

    def get(self, name: str) -> FieldReading | None:
        return self.fields.get(name)

    def value(self, name: str, min_conf: float = 0.0):
        r = self.fields.get(name)
        if r is None or not r.ok or r.confidence < min_conf:
            return None
        return r.value


class HudReader:
    def __init__(
        self,
        profile: Profile,
        ocr: OcrEngine | None = None,
        maps: list[str] | None = None,
        min_confidence: float = 0.85,
        panel_match_min: float = 0.6,
    ):
        self.profile = profile
        self.ocr = ocr or OcrEngine()
        self.maps = maps or list(DEFAULT_MAPS)
        self.min_confidence = min_confidence
        self.panel_match_min = panel_match_min

    def read(self, image: np.ndarray, fields: tuple[str, ...] = DEFAULT_FIELDS) -> HudReading:
        t0 = time.perf_counter()
        h, w = image.shape[:2]
        if (w, h) != tuple(self.profile.client_size):
            out = {f: unreadable(f"tamanho {w}x{h} ≠ perfil") for f in fields}
            return HudReading(out, False, elapsed_ms=(time.perf_counter() - t0) * 1000)

        out: dict[str, FieldReading] = {}
        for f in fields:
            try:
                out[f] = self.read_field(image, f)
            except Exception as exc:  # leitura nunca derruba o monitor
                out[f] = unreadable(f"erro: {exc}")
        return HudReading(out, True, elapsed_ms=(time.perf_counter() - t0) * 1000)

    # ------------------------------------------------------------------
    def read_field(self, image: np.ndarray, name: str) -> FieldReading:
        roi = self.profile.rois.get(name)
        if roi is None:
            return unreadable("campo não calibrado")
        crop = roi.crop(image)
        kind = FIELD_KINDS.get(name)

        if name == "hunting_time" and not self.panel_open(image):
            return absent("painel fechado")

        if kind == "glyph":
            font = self.profile.reading_font(name)
            if not font.glyphs:
                return unreadable("sem fonte calibrada")
            text, conf = glyphs.read_text(crop, font, CHARSETS.get(name))
            if not text:
                return unreadable("", 0.0)
            r = PARSERS[name](text, conf)
            return self._gate(r)

        if name == "map":
            ref_name, ref_score = self._match_map_ref(crop)
            if ref_name is not None and ref_score >= self.min_confidence:
                return FieldReading(ref_name, ref_score, ref_name, "ok")
            text, score = self.ocr.read_line(crop)
            m, ratio = match_name(text, self.maps)
            if m is None:
                return unreadable(text, score * 0.5)
            # nome bate com a lista de mapas: o OCR pode ter pontuação modesta
            conf = min(1.0, 0.5 + 0.5 * score) * ratio
            return self._gate(FieldReading(m, conf, text, "ok"))

        if name == "messages":
            lines = self.ocr.read_block(crop)
            if not lines:
                return absent()
            conf = min(s for _, s in lines)
            return FieldReading([t for t, _ in lines], conf, " | ".join(t for t, _ in lines), "ok")

        if kind == "ref":
            if self.profile.ref_image(name) is None:
                return unreadable("sem referência")
            return FieldReading(self.panel_open(image), 1.0, "", "ok")

        return unreadable("tipo de campo desconhecido")

    def _match_map_ref(self, crop: np.ndarray) -> tuple[str | None, float]:
        refs = self._map_refs_cache()
        if not refs:
            return None, 0.0
        im = glyphs.ink(crop)
        best, best_s = None, 0.0
        for name, ref in refs.items():
            if ref.shape[0] > im.shape[0] or ref.shape[1] > im.shape[1]:
                continue
            s = float(np.nan_to_num(cv2.matchTemplate(im, ref, cv2.TM_CCOEFF_NORMED)).max())
            if s > best_s:
                best, best_s = name, s
        return best, best_s

    def _map_refs_cache(self) -> dict[str, np.ndarray]:
        key = tuple(sorted((k, hash(v)) for k, v in self.profile.refs.items() if k.startswith("map:")))
        if getattr(self, "_mr_key", None) != key:
            self._mr_key = key
            self._mr = self.profile.map_refs()
        return self._mr

    def panel_open(self, image: np.ndarray) -> bool:
        """O painel Instant Hunting Log está aberto? (compara o título com a referência)."""
        ref = self.profile.ref_image("hunting_log_title")
        roi = self.profile.rois.get("hunting_log_title")
        if ref is None or roi is None:
            return True  # sem referência: tenta ler mesmo assim
        crop = roi.crop(image)
        if crop.shape != ref.shape:
            return False
        a = glyphs.ink(crop).astype(np.float32)
        b = glyphs.ink(ref).astype(np.float32)
        score = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED).max())
        return score >= self.panel_match_min

    def _gate(self, r: FieldReading) -> FieldReading:
        if r.ok and r.confidence < self.min_confidence:
            return FieldReading(None, r.confidence, r.raw, "unreadable")
        return r
