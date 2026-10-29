"""Ponto de entrada: instância única, logs, configuração, monitor, painel e bandeja.

Uso:
    musentinel               abre o painel
    musentinel --minimizado  começa só na bandeja
    musentinel --calibracao  abre só a tela de calibração
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import shutil
import sys
import threading
import time

log = logging.getLogger("musentinel")
MUTEX_NAME = "Local\\MUSentinel.InstanciaUnica"
ERROR_ALREADY_EXISTS = 183


def single_instance() -> object | None:
    """Cria o mutex nomeado. None = já existe outra instância aberta."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return h


def load_config():
    from .core.config import Config, config_path

    p = config_path()
    try:
        cfg = Config.load(p)
    except Exception as exc:
        bad = p.with_name(f"config.invalido_{time.strftime('%Y%m%d_%H%M%S')}.yaml")
        shutil.copy2(p, bad)
        log.error("config.yaml inválido (%s); cópia em %s; usando o padrão", exc, bad.name)
        return Config(), f"O config.yaml estava inválido ({exc}). Guardei uma cópia em {bad.name} e usei o padrão."
    if not p.exists():
        cfg.save(p)
    return cfg, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="musentinel")
    ap.add_argument("--minimizado", action="store_true", help="começa só na bandeja")
    ap.add_argument("--calibracao", action="store_true", help="abre só a tela de calibração")
    a = ap.parse_args(argv)

    if a.calibracao:
        from .gui.calibration import main as calibration_main

        return calibration_main()

    from .core import winapi
    from .core.logsetup import setup_logging

    winapi.enable_dpi_awareness()
    mutex = single_instance()

    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv[:1])
    app.setApplicationName("MU Sentinel")
    app.setQuitOnLastWindowClosed(False)
    if mutex is None:
        QMessageBox.information(None, "MU Sentinel", "O MU Sentinel já está aberto (veja o ícone na bandeja).")
        return 0

    logfile = setup_logging(to_console=sys.stderr is not None)
    from . import __version__

    log.info("MU Sentinel %s iniciando (admin=%s)", __version__, winapi.current_process_elevated())

    from .core.events import EventBus, EventStore
    from .gui.main_window import MainWindow

    cfg, warn = load_config()
    store = EventStore()
    bus = EventBus(store)

    def excepthook(exc_type, exc, tb):
        log.critical("exceção não tratada", exc_info=(exc_type, exc, tb))
        bus.emit("erro", f"erro inesperado: {exc_type.__name__}: {exc}", severity="aviso")

    sys.excepthook = excepthook
    threading.excepthook = lambda args: excepthook(args.exc_type, args.exc_value, args.exc_traceback)

    win = MainWindow(cfg, bus, start_hidden=a.minimizado)
    if warn:
        QMessageBox.warning(win, "Configuração", warn)
    log.info("log em %s", logfile)
    rc = app.exec()
    store.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
