"""Aprende fontes, nomes de mapa e o título do painel a partir de prints rotulados.

Só aprende quando o leitor erra (ou ainda não conhece o caractere), para não
inchar o perfil com variantes repetidas.
"""

from __future__ import annotations

import numpy as np

from . import glyphs
from .dataset import UNREADABLE, Sample, judge
from .profile import CHARSETS, Profile
from .reader import HudReader

GLYPH_FIELDS = ("hp", "coords", "exp", "hunting_time")


def learn_sample(profile: Profile, reader: HudReader, image: np.ndarray, expected: dict) -> list[str]:
    """Ensina o perfil com um print rotulado. Retorna os campos que aprenderam algo."""
    learned: list[str] = []

    ht = expected.get("hunting_time", UNREADABLE)
    if "hunting_time" in expected and ht not in (None, UNREADABLE):
        if profile.ref_image("hunting_log_title") is None and "hunting_log_title" in profile.rois:
            profile.set_ref_image("hunting_log_title", profile.rois["hunting_log_title"].crop(image))
            learned.append("hunting_log_title")

    for name in GLYPH_FIELDS:
        want = expected.get(name)
        if want in (None, UNREADABLE) or name not in profile.rois:
            continue
        want = want.replace(" ", "")
        if any(c not in CHARSETS[name] for c in want):
            continue
        got = reader.read_field(image, name)
        if judge(name, want, got)[0]:
            continue
        font = profile.font(name)
        if glyphs.learn(font, profile.rois[name].crop(image), want):
            profile.store_font(name, font)
            learned.append(name)

    want_map = expected.get("map")
    if want_map not in (None, UNREADABLE) and "map" in profile.rois:
        ref_name, score = reader._match_map_ref(profile.rois["map"].crop(image))
        if ref_name != want_map or score < reader.min_confidence:
            if profile.learn_map(want_map, profile.rois["map"].crop(image)):
                learned.append("map")
    return learned


def train(profile: Profile, samples: list[Sample], passes: int = 2) -> Profile:
    reader = HudReader(profile)
    for _ in range(passes):
        for s in samples:
            learn_sample(profile, reader, s.image(), s.expected)
    return profile
