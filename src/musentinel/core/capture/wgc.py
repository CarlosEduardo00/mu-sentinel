"""Captura via Windows Graphics Capture (pacote windows-capture).

Mantém uma sessão contínua por janela e guarda o último quadro recebido.
O WGC entrega a janela inteira (com título/borda); aqui recortamos só a área cliente.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from .. import winapi
from .base import CaptureError, Frame, WindowGoneError, WindowMinimizedError, looks_blank


class _Session:
    def __init__(self, hwnd: int, min_interval_ms: int):
        from windows_capture import WindowsCapture

        self.hwnd = hwnd
        self.lock = threading.Lock()
        self.latest: np.ndarray | None = None
        self.latest_ts = 0.0
        self.closed = False
        self.error: str | None = None

        cap = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            minimum_update_interval=min_interval_ms,
            window_hwnd=hwnd,
        )

        @cap.event
        def on_frame_arrived(frame, control):  # noqa: ARG001
            img = np.array(frame.frame_buffer[:, :, :3], copy=True)
            with self.lock:
                self.latest = img
                self.latest_ts = time.time()

        @cap.event
        def on_closed():
            self.closed = True

        try:
            self.control = cap.start_free_threaded()
        except Exception as exc:  # erro nativo vem como Exception genérica
            raise CaptureError(f"WGC não iniciou: {exc}") from exc

    def stop(self) -> None:
        try:
            self.control.stop()
        except Exception:
            pass


class WgcCapture:
    name = "wgc"

    # o monitor usa 1 quadro a cada 2 s: pedir mais ao Windows só copia imagem à toa
    def __init__(self, min_interval_ms: int = 1000, first_frame_timeout_s: float = 3.0):
        self._sessions: dict[int, _Session] = {}
        self._min_interval_ms = min_interval_ms
        self._timeout = first_frame_timeout_s

    def _session(self, hwnd: int) -> _Session:
        s = self._sessions.get(hwnd)
        if s is None or s.closed:
            if s:
                s.stop()
            s = _Session(hwnd, self._min_interval_ms)
            self._sessions[hwnd] = s
        return s

    def grab(self, hwnd: int) -> Frame:
        if not winapi.is_window(hwnd):
            self._drop(hwnd)
            raise WindowGoneError(f"janela {hwnd} não existe")
        if winapi.is_minimized(hwnd):
            raise WindowMinimizedError("janela minimizada")

        s = self._session(hwnd)
        deadline = time.time() + self._timeout
        while True:
            with s.lock:
                img = s.latest
            if img is not None:
                break
            if s.closed or time.time() > deadline:
                self._drop(hwnd)
                raise CaptureError("WGC não entregou quadro")
            time.sleep(0.02)

        img = _crop_client(hwnd, img)
        if looks_blank(img):
            raise CaptureError("quadro preto (WGC)")
        return Frame(image=img, hwnd=hwnd, backend=self.name, timestamp=s.latest_ts)

    def _drop(self, hwnd: int) -> None:
        s = self._sessions.pop(hwnd, None)
        if s:
            s.stop()

    def close(self) -> None:
        for hwnd in list(self._sessions):
            self._drop(hwnd)


def _crop_client(hwnd: int, img: np.ndarray) -> np.ndarray:
    fb = winapi.frame_bounds(hwnd)
    cr = winapi.client_rect_screen(hwnd)
    x0, y0 = cr.left - fb.left, cr.top - fb.top
    h, w = img.shape[:2]
    x0 = max(0, min(x0, w))
    y0 = max(0, min(y0, h))
    x1 = min(w, x0 + cr.width)
    y1 = min(h, y0 + cr.height)
    return np.ascontiguousarray(img[y0:y1, x0:x1])
