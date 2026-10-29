"""Conversão do texto lido em valores validados de cada campo."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

Status = Literal["ok", "absent", "unreadable"]


@dataclass(frozen=True)
class FieldReading:
    value: Any
    confidence: float
    raw: str
    status: Status

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def unreadable(raw: str = "", conf: float = 0.0) -> FieldReading:
    return FieldReading(None, conf, raw, "unreadable")


def absent(raw: str = "") -> FieldReading:
    return FieldReading(None, 0.0, raw, "absent")


_RATIO = re.compile(r"(\d{1,12})/(\d{1,12})")
_COORDS = re.compile(r"(\d{1,3}),(\d{1,3})")
_TIME = re.compile(r"(\d{2,3}):(\d{2}):(\d{2})")


def parse_ratio(raw: str, conf: float, allow_over: bool = False) -> FieldReading:
    """'805/811' → (805, 811). Atual não pode passar do máximo."""
    m = _RATIO.fullmatch(raw.replace(" ", ""))
    if not m:
        return unreadable(raw, conf)
    cur, mx = int(m.group(1)), int(m.group(2))
    if mx <= 0 or (cur > mx and not allow_over):
        return unreadable(raw, conf)
    return FieldReading((cur, mx), conf, raw, "ok")


def parse_coords(raw: str, conf: float) -> FieldReading:
    m = _COORDS.fullmatch(raw)
    if not m:
        return unreadable(raw, conf)
    x, y = int(m.group(1)), int(m.group(2))
    if x > 255 or y > 255:
        return unreadable(raw, conf)
    return FieldReading((x, y), conf, raw, "ok")


def parse_time(raw: str, conf: float) -> FieldReading:
    """'00:45:03' → 2703 segundos."""
    m = _TIME.fullmatch(raw)
    if not m:
        return unreadable(raw, conf)
    h, mi, s = (int(g) for g in m.groups())
    if mi > 59 or s > 59:
        return unreadable(raw, conf)
    return FieldReading(h * 3600 + mi * 60 + s, conf, raw, "ok")


PARSERS = {
    "hp": parse_ratio,
    "exp": parse_ratio,
    "coords": parse_coords,
    "hunting_time": parse_time,
}
