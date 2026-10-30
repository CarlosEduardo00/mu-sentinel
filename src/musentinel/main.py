"""Ponto de entrada: instância única, logs, configuração, monitor, painel e bandeja.

Uso:
    musentinel               abre o painel
    musentinel --minimizado  começa só na bandeja
    musentinel --calibracao  abre só a tela de calibração
    musentinel --smoke-test  abre, carrega a config, roda 1 ciclo do monitor e fecha (teste do .exe)
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
    ap.add_argument("--smoke-test", action="store_true", help="abre, roda 1 ciclo e fecha (código 0 = ok)")
    ap.add_argument("--assistente", action="store_true", help="abre o assistente de configuração")
    a = ap.parse_args(argv)

    if a.calibracao:
        from .gui.calibration import main as calibration_main

        return calibration_main()

    from .core import winapi
    from .core.logsetup import setup_logging

    winapi.enable_dpi_awareness()
    mutex = single_instance() if not a.smoke_test else object()

    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv[:1])
    app.setApplicationName("MU Sentinel")
    app.setQuitOnLastWindowClosed(False)
    if mutex is None:
        QMessageBox.information(None, "MU Sentinel", "O MU Sentinel já está aberto (veja o ícone na bandeja).")
        return 0

    import os

    logfile = setup_logging(logging.DEBUG if os.environ.get("MUSENTINEL_DEBUG") else logging.INFO,
                            to_console=sys.stderr is not None)
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

    if a.smoke_test:
        return smoke_test(cfg, bus, store)

    if not cfg.wizard_done or a.assistente:
        from .gui.wizard import SetupWizard

        wiz = SetupWizard(cfg)
        if wiz.exec():
            cfg = wiz.result_config()
            cfg.save()
            a.minimizado = False

    win = MainWindow(cfg, bus, start_hidden=a.minimizado)
    if warn:
        QMessageBox.warning(win, "Configuração", warn)
    log.info("log em %s", logfile)
    rc = app.exec()
    store.close()
    return rc


def smoke_test(cfg, bus, store) -> int:
    """Teste do executável empacotado: tudo carrega e o monitor completa um ciclo."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .core import paths
    from .gui.main_window import MainWindow

    result = {"rc": 1}
    win = MainWindow(cfg, bus, start_hidden=True)

    def packaged_ok() -> tuple[bool, str]:
        """Peças carregadas só na hora do uso: envio (httpx) e cofre de senhas do Windows."""
        try:
            import httpx  # noqa: F401  (Telegram e WhatsApp)
            import keyring

            backend = type(keyring.get_keyring()).__name__
        except Exception as exc:
            return False, type(exc).__name__
        return "fail" not in backend.lower() and "null" not in backend.lower(), backend

    def panels_ok() -> str:
        """OCR da tela inteira (modelo de detecção), usado nos painéis: acha um título desenhado."""
        try:
            import cv2
            import numpy as np

            from .core.panels import OCR_THREADS
            from .core.perception.ocr import OcrEngine

            img = np.full((120, 400, 3), 30, np.uint8)
            cv2.putText(img, "Inventory", (90, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (230, 230, 230), 2)
            boxes = OcrEngine(threads=OCR_THREADS).detect(img)
            return "ok" if any("inventory" in b.key for b in boxes) else f"leu {[b.text for b in boxes]}"
        except Exception as exc:
            return type(exc).__name__

    def check():
        deps_ok, keyring_name = packaged_ok()
        panels = panels_ok()
        ok = win.engine.last_cycle > 0 and deps_ok and panels == "ok"
        result["rc"] = 0 if ok else 2
        (paths.data_dir() / "smoke_test.txt").write_text(
            f"ok={ok} ciclo_ms={win.engine.cycle_ms:.0f} ciclo_max_ms={win.engine.cycle_ms_max:.0f} "
            f"slots={len(win.engine.slots)} paineis_vistos={sum(len(s.panels) for s in win.engine.snapshots())} "
            f"envio={'ok' if deps_ok else 'FALTANDO'} cofre={keyring_name} paineis={panels}\n", encoding="utf-8")
        win.engine.stop()
        win.tray.hide()
        QApplication.quit()

    import os

    QTimer.singleShot(int(float(os.environ.get("MUSENTINEL_SMOKE_S", "12")) * 1000), check)
    QApplication.instance().exec()
    store.close()
    log.info("smoke test: código %s", result["rc"])
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
