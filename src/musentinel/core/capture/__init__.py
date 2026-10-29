"""Captura de imagem das janelas do jogo."""

from __future__ import annotations

from .base import CaptureBackend, CaptureError, Frame, WindowGoneError, WindowMinimizedError
from .printwindow import PrintWindowCapture
from .wgc import WgcCapture


class FallbackCapture:
    """Tenta o WGC primeiro; se falhar, usa PrintWindow."""

    name = "auto"

    def __init__(self) -> None:
        self.primary = WgcCapture()
        self.fallback = PrintWindowCapture()

    def grab(self, hwnd: int) -> Frame:
        try:
            return self.primary.grab(hwnd)
        except (WindowGoneError, WindowMinimizedError):
            raise
        except CaptureError:
            return self.fallback.grab(hwnd)

    def close(self) -> None:
        self.primary.close()
        self.fallback.close()


def make_backend(kind: str = "auto") -> CaptureBackend:
    if kind == "wgc":
        return WgcCapture()
    if kind == "printwindow":
        return PrintWindowCapture()
    return FallbackCapture()


__all__ = [
    "CaptureBackend",
    "CaptureError",
    "FallbackCapture",
    "Frame",
    "PrintWindowCapture",
    "WgcCapture",
    "WindowGoneError",
    "WindowMinimizedError",
    "make_backend",
]
