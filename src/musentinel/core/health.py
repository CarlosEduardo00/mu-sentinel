"""Saúde do client, só com APIs de leitura do Windows.

- processo vivo (psutil)
- janela respondendo (IsHungAppWindow + SendMessageTimeout(WM_NULL))
- conexão TCP do processo com o servidor (tabela de conexões do Windows)
- quadro mudou (comparação de miniaturas)
- internet (abre uma conexão TCP com DNS públicos)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import socket
import threading
import time
from collections import defaultdict

import cv2
import numpy as np
import psutil

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                       ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = ctypes.c_size_t
user32.IsHungAppWindow.argtypes = [wt.HWND]
user32.OpenInputDesktop.restype = wt.HANDLE
user32.GetUserObjectInformationW.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                             ctypes.POINTER(wt.DWORD)]
user32.CloseDesktop.argtypes = [wt.HANDLE]

WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
ERROR_TIMEOUT = 1460


def process_alive(pid: int, expected_name: str | None = None) -> bool:
    try:
        p = psutil.Process(pid)
        if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
            return False
        if expected_name:
            return p.name().lower() == expected_name.lower()
        return True
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True  # existe, só não deixa ver detalhes


def window_hung(hwnd: int, timeout_ms: int = 1000) -> bool:
    """True se o Windows considera a janela 'sem responder'."""
    if user32.IsHungAppWindow(hwnd):
        return True
    res = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(res))
    if ok:
        return False
    # erro 5 (acesso negado/UIPI) não diz nada; só timeout conta como travado
    return ctypes.get_last_error() == ERROR_TIMEOUT


def tcp_by_pid() -> dict[int, set[tuple[str, int]]]:
    """Conexões TCP ESTABLISHED com endereço remoto fora da máquina, por PID."""
    out: dict[int, set[tuple[str, int]]] = defaultdict(set)
    try:
        conns = psutil.net_connections(kind="tcp")
    except psutil.AccessDenied:
        return {}
    for c in conns:
        if c.status != psutil.CONN_ESTABLISHED or not c.raddr or c.pid is None:
            continue
        ip = c.raddr.ip
        if ip.startswith("127.") or ip == "::1":
            continue
        out[c.pid].add((ip, c.raddr.port))
    return out


class ConnectionTracker:
    """Guarda as conexões do client enquanto ele está claramente online (referência).

    Desconectado = nenhuma conexão de referência e nenhuma conexão nova enquanto há
    sinal de jogo online. Antes de existir referência o resultado é desconhecido (None).
    """

    def __init__(self) -> None:
        self.reference: set[tuple[str, int]] = set()

    def reset(self) -> None:
        self.reference = set()

    def update(self, conns: set[tuple[str, int]], online_evidence: bool) -> bool | None:
        if not self.reference:
            if conns and online_evidence:
                self.reference = set(conns)
                return True
            return None
        if conns & self.reference:
            if online_evidence:
                self.reference |= conns
            return True
        if conns and online_evidence:
            # trocou de servidor/canal: adota a nova conexão como referência
            self.reference = set(conns)
            return True
        return False


class FrameWatcher:
    """Detecta render congelado: miniatura idêntica por muito tempo."""

    def __init__(self, diff_min: float = 0.25) -> None:
        self.diff_min = diff_min
        self._last: np.ndarray | None = None
        self.last_change = 0.0

    @staticmethod
    def signature(img: np.ndarray) -> np.ndarray:
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        return cv2.resize(g, (96, 72), interpolation=cv2.INTER_AREA).astype(np.float32)

    def update(self, img: np.ndarray, now: float) -> float:
        """Retorna há quantos segundos o quadro não muda."""
        sig = self.signature(img)
        if self._last is None or float(np.abs(sig - self._last).mean()) >= self.diff_min:
            self.last_change = now
        self._last = sig
        return now - self.last_change

    def reset(self) -> None:
        self._last = None


def internet_ok(timeout: float = 2.0) -> bool:
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53), ("208.67.222.222", 443)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


class InternetProbe:
    """Testa a internet em segundo plano a cada N s (o ciclo do monitor não espera rede)."""

    def __init__(self, every_s: float = 10.0) -> None:
        self.every_s = every_s
        self.ok: bool | None = None
        self.fails = 0
        self.last = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="internet", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def check_now(self) -> bool:
        ok = internet_ok()
        self.fails = 0 if ok else self.fails + 1
        self.ok = ok if ok or self.fails >= 2 else self.ok  # 2 falhas seguidas para dizer "sem internet"
        if self.ok is None:
            self.ok = ok
        self.last = time.time()
        return ok

    def _run(self) -> None:
        while not self._stop.is_set():
            self.check_now()
            self._stop.wait(self.every_s)


def session_locked() -> bool:
    """Tela bloqueada (Win+L) ou outra área de trabalho segura ativa."""
    h = user32.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
    if not h:
        return True
    try:
        buf = ctypes.create_unicode_buffer(256)
        n = wt.DWORD()
        if user32.GetUserObjectInformationW(h, 2, buf, ctypes.sizeof(buf), ctypes.byref(n)):  # UOI_NAME
            return buf.value.lower() != "default"
        return False
    finally:
        user32.CloseDesktop(h)


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def user_idle_s() -> float:
    """Segundos desde o último teclado/mouse do usuário (qualquer janela)."""
    li = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    if not user32.GetLastInputInfo(ctypes.byref(li)):
        return 0.0
    tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((tick - li.dwTime) & 0xFFFFFFFF) / 1000.0
