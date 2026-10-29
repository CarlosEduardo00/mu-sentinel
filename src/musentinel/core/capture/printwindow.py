"""Captura via PrintWindow(PW_RENDERFULLCONTENT): pede ao DWM o conteúdo da janela.

Funciona com a janela coberta; não funciona com a janela minimizada.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

import numpy as np

from .. import winapi
from .base import CaptureError, Frame, WindowGoneError, WindowMinimizedError, looks_blank

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = winapi.user32

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.GetDIBits.argtypes = [
    wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT
]
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.PrintWindow.restype = wt.BOOL


class PrintWindowCapture:
    name = "printwindow"

    def grab(self, hwnd: int) -> Frame:
        if not winapi.is_window(hwnd):
            raise WindowGoneError(f"janela {hwnd} não existe")
        if winapi.is_minimized(hwnd):
            raise WindowMinimizedError("janela minimizada")

        r = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(r))
        w, h = r.right, r.bottom
        if w <= 0 or h <= 0:
            raise CaptureError("área cliente vazia")

        hdc_win = user32.GetDC(hwnd)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
        bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
        old = gdi32.SelectObject(hdc_mem, bmp)
        try:
            ok = user32.PrintWindow(hwnd, hdc_mem, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
            if not ok:
                raise CaptureError(f"PrintWindow falhou (erro {ctypes.get_last_error()})")
            bi = BITMAPINFOHEADER()
            bi.biSize = ctypes.sizeof(bi)
            bi.biWidth = w
            bi.biHeight = -h  # de cima para baixo
            bi.biPlanes = 1
            bi.biBitCount = 32
            bi.biCompression = BI_RGB
            buf = np.empty((h, w, 4), dtype=np.uint8)
            lines = gdi32.GetDIBits(
                hdc_mem, bmp, 0, h, buf.ctypes.data_as(ctypes.c_void_p), ctypes.byref(bi), DIB_RGB_COLORS
            )
            if lines != h:
                raise CaptureError("GetDIBits não devolveu a imagem inteira")
        finally:
            gdi32.SelectObject(hdc_mem, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(hwnd, hdc_win)

        img = np.ascontiguousarray(buf[:, :, :3])
        if looks_blank(img):
            raise CaptureError("quadro preto (PrintWindow não obteve o conteúdo)")
        return Frame(image=img, hwnd=hwnd, backend=self.name)

    def close(self) -> None:
        pass
