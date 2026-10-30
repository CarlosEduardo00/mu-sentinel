"""Funções do Windows usadas só em modo leitura (janelas, processos, DPI).

Nada aqui lê ou escreve memória do jogo.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
kernel32.CloseHandle.argtypes = [wt.HANDLE]

for _name, _args, _res in (
    ("IsWindowVisible", [wt.HWND], wt.BOOL),
    ("GetWindowTextLengthW", [wt.HWND], ctypes.c_int),
    ("GetWindowTextW", [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
    ("GetWindowThreadProcessId", [wt.HWND, ctypes.POINTER(wt.DWORD)], wt.DWORD),
    ("IsWindow", [wt.HWND], wt.BOOL),
    ("IsIconic", [wt.HWND], wt.BOOL),
    ("GetClientRect", [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
    ("ClientToScreen", [wt.HWND, ctypes.POINTER(wt.POINT)], wt.BOOL),
    ("GetWindowRect", [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
):
    _f = getattr(user32, _name)
    _f.argtypes, _f.restype = _args, _res

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20
DWMWA_EXTENDED_FRAME_BOUNDS = 9

_dpi_set = False


def enable_dpi_awareness() -> None:
    """Faz o processo enxergar pixels físicos (senão o Windows escala as coordenadas)."""
    global _dpi_set
    if _dpi_set:
        return
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            user32.SetProcessDPIAware()
    _dpi_set = True


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    process_name: str
    client_size: tuple[int, int]
    minimized: bool
    elevated: bool | None  # None = não deu para consultar


def get_window_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def get_pid(hwnd: int) -> int:
    """PID dono da janela. 0 = o Windows não informou (ver list_windows)."""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_window(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def client_rect_screen(hwnd: int) -> Rect:
    """Área cliente (sem borda/título) em coordenadas de tela."""
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return Rect(pt.x, pt.y, pt.x + r.right, pt.y + r.bottom)


def frame_bounds(hwnd: int) -> Rect:
    """Retângulo visível da janela segundo o DWM (é o que o WGC captura)."""
    r = wt.RECT()
    hr = dwmapi.DwmGetWindowAttribute(
        wt.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)
    )
    if hr != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return Rect(r.left, r.top, r.right, r.bottom)


def process_name(pid: int) -> str:
    import psutil

    try:
        return psutil.Process(pid).name()
    except Exception as exc:  # processo elevado/protegido: sem nome não é motivo para descartar
        log.debug("nome do processo %s indisponível: %s", pid, type(exc).__name__)
        return ""


def is_process_elevated(pid: int) -> bool | None:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        tok = wt.HANDLE()
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            elev = wt.DWORD()
            size = wt.DWORD()
            ok = advapi32.GetTokenInformation(
                tok, TokenElevation, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(size)
            )
            return bool(elev.value) if ok else None
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def current_process_elevated() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


GW_HWNDPREV = 3
DWMWA_CLOAKED = 14


def is_cloaked(hwnd: int) -> bool:
    v = wt.DWORD()
    hr = dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    return hr == 0 and v.value != 0


def covered_fraction(hwnd: int) -> float:
    """Fração (0..1) da área cliente coberta por outras janelas visíveis acima dela."""
    import numpy as np

    cr = client_rect_screen(hwnd)
    if cr.width <= 0 or cr.height <= 0:
        return 0.0
    step = 8  # grade de 8 px basta para estimar
    gw, gh = max(1, cr.width // step), max(1, cr.height // step)
    mask = np.zeros((gh, gw), dtype=bool)
    user32.GetWindow.restype = wt.HWND
    h = user32.GetWindow(wt.HWND(hwnd), GW_HWNDPREV)
    guard = 0
    while h and guard < 2000:
        guard += 1
        if user32.IsWindowVisible(h) and not user32.IsIconic(h) and not is_cloaked(h):
            r = frame_bounds(h)
            x0 = max(0, (r.left - cr.left) // step)
            y0 = max(0, (r.top - cr.top) // step)
            x1 = min(gw, -(-(r.right - cr.left) // step))
            y1 = min(gh, -(-(r.bottom - cr.top) // step))
            if x1 > x0 and y1 > y0:
                mask[y0:y1, x0:x1] = True
        h = user32.GetWindow(h, GW_HWNDPREV)
    return float(mask.mean())


def monitor_off() -> None:
    """Desliga o(s) monitor(es) como o Windows faz ao economizar energia.
    Qualquer movimento do mouse ou tecla liga de novo."""
    HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER = 0xFFFF, 0x0112, 0xF170
    user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)


_EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def list_windows(title: str = "MU", process: str | None = "main.exe",
                 stats: dict | None = None) -> list[WindowInfo]:
    """Janelas visíveis de nível superior com o título exato (e o processo, se informado).

    `stats["sem_dono"]` recebe quantas janelas com o título certo o Windows não disse de
    qual processo são. Isso acontece quando o anti-cheat do jogo (GameGuard) restringe este
    programa. O app não tenta contornar: só conta, para avisar o usuário.
    """
    found: list[int] = []
    enum_stats = {"total": 0, "erros": 0}
    own_pid = kernel32.GetCurrentProcessId()

    def cb(hwnd, _):
        # exceção dentro do callback faria o EnumWindows parar no meio sem avisar
        try:
            enum_stats["total"] += 1
            # janelas do próprio app: GetWindowText nelas manda mensagem para a thread da
            # GUI e pode travar; não precisam ser olhadas
            if hwnd and user32.IsWindowVisible(hwnd) and get_pid(hwnd) != own_pid \
                    and get_window_text(hwnd) == title:
                found.append(hwnd)
        except Exception:
            enum_stats["erros"] += 1
        return True

    ok = user32.EnumWindows(_EnumProc(cb), 0)
    log.debug("EnumWindows ok=%s janelas=%d erros=%d com título %r=%d", ok, enum_stats["total"], enum_stats["erros"],
              title, len(found))
    out: list[WindowInfo] = []
    hidden = 0
    for hwnd in found:
        pid = get_pid(hwnd)
        if not pid:
            hidden += 1
            continue
        pname = process_name(pid)
        if process and pname and pname.lower() != process.lower():
            log.debug("janela %s ignorada: processo %r (PID %s) não é %r", hwnd, pname, pid, process)
            continue
        r = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(r))
        out.append(
            WindowInfo(
                hwnd=hwnd,
                pid=pid,
                title=title,
                process_name=pname,
                client_size=(r.right, r.bottom),
                minimized=is_minimized(hwnd),
                elevated=is_process_elevated(pid),
            )
        )
    if stats is not None:
        stats["sem_dono"] = hidden
    return out
