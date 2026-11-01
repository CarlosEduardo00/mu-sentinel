"""Aviso de versão nova e atualização pela tela (a lógica fica em core/updater.py)."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QSystemTrayIcon,
    QTextBrowser, QVBoxLayout,
)

from .. import __version__
from ..core import paths, updater
from ..core.updater import Release, UpdateCancelled, UpdateError

log = logging.getLogger(__name__)


class OfferDialog(QDialog):
    LATER, UPDATE, SKIP = 0, 1, 2

    def __init__(self, rel: Release, parent=None, blocked_reason: str = ""):
        super().__init__(parent)
        self.choice = self.LATER
        self.setWindowTitle("Atualização disponível")
        self.resize(620, 520)
        v = QVBoxLayout(self)
        head = QLabel(f"<b style='font-size:15px'>MU Sentinel {rel.version} está disponível</b>"
                      f"<br>Você tem a versão {__version__}. Novidades:")
        v.addWidget(head)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(rel.notes)
        v.addWidget(notes, 1)
        if blocked_reason:
            why = QLabel(blocked_reason)
            why.setWordWrap(True)
            why.setStyleSheet("color:#b26a00;")
            v.addWidget(why)
        else:
            tip = QLabel("A configuração, o Telegram e os slots continuam como estão. O app fecha e abre de novo "
                         "sozinho em alguns segundos.")
            tip.setWordWrap(True)
            tip.setStyleSheet("color:#777;")
            v.addWidget(tip)
        row = QHBoxLayout()
        skip = QPushButton("Pular esta versão")
        skip.setToolTip("Não avisa de novo sobre esta versão (avisa quando sair a próxima)")
        skip.clicked.connect(lambda: self._done(self.SKIP))
        later = QPushButton("Depois")
        later.clicked.connect(lambda: self._done(self.LATER))
        go = QPushButton("Abrir página de download" if blocked_reason else "Atualizar agora")
        go.setDefault(True)
        go.clicked.connect(lambda: self._done(self.UPDATE))
        row.addWidget(skip)
        row.addStretch()
        row.addWidget(later)
        row.addWidget(go)
        v.addLayout(row)

    def _done(self, choice: int) -> None:
        self.choice = choice
        self.accept()


class UpdateController(QObject):
    """Procura versão nova ao abrir (e a cada 12 h), oferece, baixa e passa a troca para o exe novo."""

    checked = Signal(object)
    progressed = Signal(int, int)
    downloaded = Signal(object)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.available: Release | None = None
        self._busy = False
        self._cancel = False
        self._pending = False
        self._offered: set[str] = set()
        self._dlg: QProgressDialog | None = None
        self.checked.connect(self._on_checked)
        self.progressed.connect(self._on_progress)
        self.downloaded.connect(self._on_downloaded)
        self._timer = QTimer(self)
        self._timer.setInterval(updater.CHECK_EVERY_S * 1000)
        self._timer.timeout.connect(self.check)

    def start(self) -> None:
        if not updater.can_self_update():
            return
        QTimer.singleShot(60_000, lambda: threading.Thread(target=updater.cleanup, daemon=True,
                                                           name="limpa-atualizacao").start())
        if updater.enabled():
            QTimer.singleShot(30_000, self.check)
            self._timer.start()

    # ------------------------------------------------------------------ consulta
    def check(self, manual: bool = False) -> None:
        if self._busy or (not manual and not self.win.cfg.check_updates):
            return
        if not updater.enabled():
            if manual:
                QMessageBox.information(self.win, "Atualizações", "Esta cópia não tem o endereço de atualizações.")
            return
        self._busy = True

        def work():
            try:
                rel, err = updater.check(), None
            except UpdateError as exc:
                rel, err = None, str(exc)
            except Exception as exc:
                rel, err = None, f"erro inesperado ({type(exc).__name__})"
            self.checked.emit((rel, err, manual))

        threading.Thread(target=work, daemon=True, name="procura-atualizacao").start()

    def _on_checked(self, payload) -> None:
        rel, err, manual = payload
        self._busy = False
        if err:
            log.info("procura de atualização: %s", err)
            if manual:
                QMessageBox.warning(self.win, "Atualizações", f"Não consegui procurar atualizações: {err}.")
            return
        self.available = rel
        self.win.set_update_link(rel.version if rel else None)
        if rel is None:
            if manual:
                QMessageBox.information(self.win, "Atualizações", f"Você já está na versão mais nova ({__version__}).")
            return
        log.info("versão nova disponível: %s", rel.version)
        if not manual and (rel.version == self.win.cfg.skipped_version or rel.version in self._offered):
            return
        if manual or (self.win.isVisible() and not self.win.isMinimized()):
            self.offer()
        else:
            self._pending = True
            self.win.tray.showMessage("Atualização do MU Sentinel",
                                      f"Versão {rel.version} disponível: abra o app para atualizar.",
                                      QSystemTrayIcon.MessageIcon.Information, 10000)

    def on_window_shown(self) -> None:
        if self._pending:
            self._pending = False
            QTimer.singleShot(1500, self.offer)

    # ------------------------------------------------------------------ oferta
    def _blocked_reason(self, rel: Release) -> str:
        if not updater.can_self_update():
            return "Rodando pelo código-fonte: atualize com git pull."
        if not rel.zip_url:
            return "Esta versão não tem o arquivo para Windows publicado ainda."
        if not updater.can_write(paths.app_dir()):
            return (f"Sem permissão para gravar em {paths.app_dir()}. Baixe o zip pela página e extraia por cima "
                    "da pasta atual (com o app fechado).")
        return ""

    def offer(self) -> None:
        rel = self.available
        if rel is None:
            return
        if QApplication.activeModalWidget() is not None:  # outra janela aberta (ex.: novidades): espera
            QTimer.singleShot(2000, self.offer)
            return
        self._offered.add(rel.version)
        reason = self._blocked_reason(rel)
        d = OfferDialog(rel, self.win, reason)
        d.exec()
        if d.choice == OfferDialog.SKIP:
            cfg = self.win.cfg.model_copy(deep=True)
            cfg.skipped_version = rel.version
            self.win.apply_config(cfg)
        elif d.choice == OfferDialog.UPDATE:
            if reason:
                QDesktopServices.openUrl(QUrl(rel.page_url))
            else:
                self._download(rel)

    # ------------------------------------------------------------------ download e troca
    def _download(self, rel: Release) -> None:
        self._cancel = False
        dlg = QProgressDialog(f"Baixando o MU Sentinel {rel.version}…", "Cancelar", 0, 100, self.win)
        dlg.setWindowTitle("Atualização")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.canceled.connect(lambda: setattr(self, "_cancel", True))
        dlg.setValue(0)
        self._dlg = dlg
        last = {"pct": -1}

        def progress(got: int, total: int) -> None:
            pct = int(got * 100 / total) if total else -1
            if pct != last["pct"]:
                last["pct"] = pct
                self.progressed.emit(got, total)

        def work():
            try:
                root, err = updater.download(rel, progress=progress, cancel=lambda: self._cancel), None
            except UpdateCancelled:
                root, err = None, ""
            except UpdateError as exc:
                root, err = None, str(exc)
            except Exception as exc:
                log.exception("download da atualização")
                root, err = None, f"erro inesperado ({type(exc).__name__})"
            self.downloaded.emit((root, err, rel))

        threading.Thread(target=work, daemon=True, name="baixa-atualizacao").start()

    def _on_progress(self, got: int, total: int) -> None:
        if self._dlg is None:
            return
        if total:
            self._dlg.setMaximum(100)
            self._dlg.setValue(int(got * 100 / total))
            self._dlg.setLabelText(f"Baixando o MU Sentinel {self.available.version if self.available else ''}… "
                                   f"{got / 1e6:.0f} de {total / 1e6:.0f} MB")
        else:
            self._dlg.setMaximum(0)

    def _on_downloaded(self, payload) -> None:
        root, err, rel = payload
        if self._dlg is not None:
            self._dlg.hide()
            self._dlg.deleteLater()
            self._dlg = None
        if err == "":
            return  # cancelado
        if err:
            QMessageBox.warning(self.win, "Atualização", f"A atualização não foi feita: {err}.")
            return
        QMessageBox.information(self.win, "Atualização",
                                f"Versão {rel.version} baixada e conferida. O MU Sentinel vai fechar e abrir de "
                                "novo já atualizado (leva alguns segundos).")
        try:
            updater.launch_finisher(root, paths.app_dir())
        except OSError as exc:
            QMessageBox.warning(self.win, "Atualização", f"Não consegui abrir a versão nova: {exc}.")
            return
        log.info("fechando para concluir a atualização para %s", rel.version)
        self.win.quit_now()
