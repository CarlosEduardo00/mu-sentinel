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
UNKNOWN_CHAR_CONF = 0.3  # confiança que o template devolve quando sobra tinta sem caractere
VERDICT_OK_S = 120  # o OCR confirmou este texto: aceita o mesmo texto sem OCR por 2 min
VERDICT_FAIL_S = 30  # o OCR não confirmou: não tenta de novo o mesmo texto por 30 s


def _is_subsequence(part: str, whole: str) -> bool:
    it = iter(whole)
    return all(c in it for c in part)


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
        ocr_fallback: bool = True,
    ):
        self.ocr_fallback = ocr_fallback
        # decisões recentes do OCR de reserva por (campo, texto que o modelo leu): o HUD costuma mostrar
        # o mesmo número por muito tempo; sem isso o OCR repetia a mesma leitura a cada ciclo (CPU à toa)
        self._verdicts: dict[tuple[str, str], tuple[float, FieldReading | None]] = {}
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
                out[f] = unreadable(f"erro: {type(exc).__name__}: {exc}")
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
            text, conf, extent = glyphs.read_text_ex(crop, font, CHARSETS.get(name))
            if not text:
                return unreadable("", 0.0)
            if not self._in_place(name, extent):
                # texto fora do alinhamento de sempre: provavelmente meio coberto por um menu
                return unreadable(text, min(conf, 0.4))
            return self._glyph_result(name, crop, text, conf)

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

    def _glyph_result(self, name: str, crop: np.ndarray, text: str, conf: float) -> FieldReading:
        r = self._gate(PARSERS[name](text, conf))
        if r.ok and self.profile.missing_chars(name):
            # A fonte deste campo ainda não tem todos os dígitos próprios (os que faltam vêm
            # emprestados de outro campo, com outro fundo). Um dígito desconhecido pode casar
            # com o modelo errado (6 lido como 5): só vale se o OCR confirmar o mesmo valor.
            return self._ocr_confirm(name, crop, r) if self.ocr_fallback else unreadable(text, UNKNOWN_CHAR_CONF)
        if not r.ok and self.ocr_fallback:
            # valor impossível ou incompleto ("208/28"): o OCR lê de novo; só vale se as duas escalas
            # concordarem e o resultado contiver, na ordem, o que o modelo já tinha lido
            r = self._ocr_rescue(name, crop, text) or r
        return r

    def read_field_at(self, image: np.ndarray, name: str, roi) -> FieldReading:
        """Lê um campo de dígitos numa região dada (ex.: tempo de caça no Instant Hunting Log desta
        janela, que o usuário pode ter arrastado). O painel já foi achado aberto por quem chamou."""
        crop = roi.crop(image)
        if crop.size == 0:
            return unreadable("região fora da janela")
        font = self.profile.reading_font(name)
        if not font.glyphs:
            return unreadable("sem fonte calibrada")
        try:
            text, conf, _ = glyphs.read_text_ex(crop, font, CHARSETS.get(name))
        except Exception as exc:
            return unreadable(f"erro: {type(exc).__name__}: {exc}")
        if not text:
            return unreadable("", 0.0)
        return self._glyph_result(name, crop, text, conf)

    def _remembered(self, key: tuple[str, str]) -> tuple[bool, FieldReading | None]:
        hit = self._verdicts.get(key)
        if hit is None:
            return False, None
        ts, val = hit
        ttl = VERDICT_OK_S if val is not None else VERDICT_FAIL_S
        if time.monotonic() - ts > ttl:
            self._verdicts.pop(key, None)
            return False, None
        return True, val

    def _remember(self, key: tuple[str, str], val: FieldReading | None) -> None:
        if len(self._verdicts) > 512:
            self._verdicts.clear()
        self._verdicts[key] = (time.monotonic(), val)

    def _ocr_confirm(self, name: str, crop: np.ndarray, r: FieldReading) -> FieldReading:
        """Template e OCR (duas escalas) precisam dar o mesmo valor; senão, ilegível."""
        key = (name, "confirm:" + r.raw)
        known, val = self._remembered(key)
        if known:
            return r if val is not None else unreadable(r.raw, 0.4)
        out = self._ocr_confirm_now(name, crop, r)
        self._remember(key, out if out.ok else None)
        return out

    def _ocr_confirm_now(self, name: str, crop: np.ndarray, r: FieldReading) -> FieldReading:
        cs = CHARSETS[name]
        text, score = self.ocr.read_number(crop, cs)
        if text and score >= self.min_confidence:
            o = PARSERS[name](text, score)
            if o.ok and o.value == r.value:
                return r
        # segunda chance: uma leitura simples do OCR igual à do modelo (dois leitores independentes
        # concordando). Ajuda em vírgula pequena, que uma das duas escalas do OCR às vezes perde.
        line, s2 = self.ocr.read_line(crop)
        if "," in cs and "." not in cs:
            line = line.replace(".", ",")
        line = "".join(c for c in line if c in cs)
        if line and s2 >= 0.9:
            o = PARSERS[name](line, s2)
            if o.ok and o.value == r.value:
                return r
        return unreadable(r.raw, 0.4)

    def _ocr_rescue(self, name: str, crop: np.ndarray, partial: str) -> FieldReading | None:
        """O template achou tinta que não reconhece (dígito ainda não aprendido).

        Lê com OCR em duas escalas e só aceita se: as duas concordam, o valor é
        válido e contém, na ordem, tudo o que o template já tinha lido.
        """
        key = (name, "rescue:" + partial)
        known, val = self._remembered(key)
        if known:
            return val
        out = self._ocr_rescue_now(name, crop, partial)
        self._remember(key, out)
        return out

    def _ocr_rescue_now(self, name: str, crop: np.ndarray, partial: str) -> FieldReading | None:
        text, score = self.ocr.read_number(crop, CHARSETS[name])
        if not text or score < 0.9 or not _is_subsequence(partial, text):
            return None
        r = PARSERS[name](text, score * 0.95)
        if not r.ok:
            return None
        return FieldReading(r.value, r.confidence, f"{text} (OCR)", "ok")

    def _in_place(self, name: str, extent: tuple[int, int] | None) -> bool:
        anchor = self.profile.anchor(name)
        if anchor is None or extent is None:
            return True
        side, pos, tol = anchor
        x0, x1 = extent
        v = {"left": x0, "right": x1, "center": (x0 + x1) / 2}[side]
        return abs(v - pos) <= tol

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
