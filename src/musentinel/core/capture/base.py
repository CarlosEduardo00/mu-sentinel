"""Interface comum de captura de imagem da janela do jogo."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


class CaptureError(Exception):
    """Falha genérica de captura."""


class WindowGoneError(CaptureError):
    """A janela não existe mais."""


class WindowMinimizedError(CaptureError):
    """Janela minimizada não renderiza; não há o que capturar."""


@dataclass(frozen=True)
class Frame:
    image: np.ndarray  # BGR uint8, só a área cliente da janela
    hwnd: int
    backend: str
    timestamp: float = field(default_factory=time.time)

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.image.shape[:2]
        return w, h


class CaptureBackend(Protocol):
    name: str

    def grab(self, hwnd: int) -> Frame: ...

    def close(self) -> None: ...


def looks_blank(image: np.ndarray) -> bool:
    """Quadro todo preto (ou quase) costuma indicar captura que falhou em silêncio."""
    return image.size == 0 or float(image.max()) < 8
