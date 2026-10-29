"""Energia: avisa se o PC pode suspender e mantém o PC acordado enquanto monitora.

Em notebooks com Modern Standby (S0), apagar a tela por tempo ocioso ou fechar a
tampa coloca o Windows em espera: o jogo e o app param juntos e nenhum alerta sai.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import uuid

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

SUB_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
STANDBY_IDLE = "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"
SUB_VIDEO = "7516b95f-f776-4464-8c53-06167f40cc99"
VIDEO_IDLE = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, s: str) -> GUID:
        b = uuid.UUID(s).bytes_le
        return cls.from_buffer_copy(b)


def keep_awake(system: bool = True, display: bool = False) -> None:
    """Vale para a thread que chamar, enquanto ela viver (chamar na thread do monitor)."""
    flags = ES_CONTINUOUS
    if system:
        flags |= ES_SYSTEM_REQUIRED
    if display:
        flags |= ES_DISPLAY_REQUIRED
    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def release_awake() -> None:
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def modern_standby() -> bool:
    """True se o PC usa Modern Standby (S0 Low Power Idle)."""

    class SPC(ctypes.Structure):  # SYSTEM_POWER_CAPABILITIES (só os campos até AoAc importam)
        _fields_ = [(n, ctypes.c_ubyte) for n in (
            "PowerButtonPresent", "SleepButtonPresent", "LidPresent", "SystemS1", "SystemS2", "SystemS3",
            "SystemS4", "SystemS5", "HiberFilePresent", "FullWake", "VideoDimPresent", "ApmPresent",
            "UpsPresent", "ThermalControl", "ProcessorThrottle", "ProcessorMinThrottle",
            "ProcessorMaxThrottle", "FastSystemS4", "Hiberboot", "WakeAlarmPresent", "AoAc")] + [
            ("rest", ctypes.c_ubyte * 64)]

    s = SPC()
    try:
        if ctypes.windll.powrprof.GetPwrCapabilities(ctypes.byref(s)):
            return bool(s.AoAc)
    except (OSError, AttributeError):
        pass
    return False


def _read_timeouts(sub: str, setting: str) -> tuple[int | None, int | None]:
    """(tomada, bateria) em segundos; 0 = nunca."""
    pp = ctypes.windll.powrprof
    scheme = ctypes.POINTER(GUID)()
    if pp.PowerGetActiveScheme(None, ctypes.byref(scheme)) != 0:
        return None, None
    try:
        g_sub, g_set = GUID.of(sub), GUID.of(setting)
        ac, dc = wt.DWORD(), wt.DWORD()
        r1 = pp.PowerReadACValueIndex(None, scheme, ctypes.byref(g_sub), ctypes.byref(g_set), ctypes.byref(ac))
        r2 = pp.PowerReadDCValueIndex(None, scheme, ctypes.byref(g_sub), ctypes.byref(g_set), ctypes.byref(dc))
        return (ac.value if r1 == 0 else None, dc.value if r2 == 0 else None)
    finally:
        ctypes.windll.kernel32.LocalFree(scheme)


def _fmt(s: int) -> str:
    return f"{s // 60} min" if s >= 60 else f"{s} s"


def power_warnings() -> list[str]:
    """Avisos para mostrar na UI. Lista vazia = nada a avisar."""
    out: list[str] = []
    try:
        sleep_ac, _ = _read_timeouts(SUB_SLEEP, STANDBY_IDLE)
        video_ac, _ = _read_timeouts(SUB_VIDEO, VIDEO_IDLE)
        ms = modern_standby()
    except Exception:
        return out
    if sleep_ac:
        out.append(f"O Windows entra em suspensão após {_fmt(sleep_ac)} na tomada (o app mantém o PC "
                   "acordado enquanto roda, mas confira o plano de energia).")
    if ms:
        if video_ac:
            out.append(f"Este PC usa Modern Standby: quando a tela apagar ({_fmt(video_ac)} na tomada) o "
                       "Windows pode entrar em espera e o jogo e os alertas param. Ative 'manter a tela "
                       "ligada' nas Configurações ou mude 'Desligar a tela' para Nunca.")
        else:
            out.append("Este PC usa Modern Standby: fechar a tampa ou apagar a tela manualmente coloca o "
                       "Windows em espera e para os alertas.")
    return out
