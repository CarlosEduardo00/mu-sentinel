"""Tela da atualização: oferta, "Pular esta versão", download e passagem para o exe novo."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from musentinel.core import updater  # noqa: E402
from musentinel.core.config import Config  # noqa: E402
from musentinel.core.updater import Release, UpdateError  # noqa: E402
from musentinel.gui import update_dialog  # noqa: E402
from musentinel.gui.update_dialog import OfferDialog, UpdateController  # noqa: E402

REL = Release("0.3.0", "## Versão 0.3.0\n\n- novidade", "https://github.com/dono/mu-sentinel/releases/tag/v0.3.0",
              "https://dl/app.zip", 10, "a" * 64, None)


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a
    for w in QApplication.topLevelWidgets():  # janela viva no fim do Python derruba o processo no Windows
        w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


class FakeTray:
    def __init__(self):
        self.msgs = []

    def showMessage(self, title, body, *a):  # noqa: N802
        self.msgs.append(body)


class FakeWin(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = Config()
        self.tray = FakeTray()
        self.link = "nunca chamado"
        self.quit_called = False

    def set_update_link(self, v):
        self.link = v

    def apply_config(self, cfg):
        self.cfg = cfg

    def quit_now(self):
        self.quit_called = True


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert cond()


@pytest.fixture
def ctl(app, monkeypatch):
    monkeypatch.setattr(updater, "REPO", "dono/mu-sentinel")
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    monkeypatch.setattr(updater, "can_write", lambda p: True)
    w = FakeWin()
    c = UpdateController(w)
    c.offers = []

    def fake_exec(choice):
        def run(self):
            c.offers.append(self)
            self.choice = choice
            return 1
        return run

    c.set_choice = lambda ch: monkeypatch.setattr(OfferDialog, "exec", fake_exec(ch))
    c.set_choice(OfferDialog.LATER)
    yield c
    wait_for(lambda: not c._busy)
    c._timer.stop()
    c.offers.clear()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_hidden_window_gets_tray_message_then_offer_when_shown(ctl, monkeypatch):
    monkeypatch.setattr(updater, "check", lambda: REL)
    ctl.check()
    wait_for(lambda: ctl.available is not None)
    assert ctl.win.link == "0.3.0" and "0.3.0" in ctl.win.tray.msgs[0] and not ctl.offers
    ctl.on_window_shown()
    wait_for(lambda: ctl.offers, timeout=4)
    # "Depois": não oferece de novo sozinho nesta sessão
    ctl.check()
    wait_for(lambda: not ctl._busy)
    assert len(ctl.offers) == 1


def test_skip_is_saved_and_respected(ctl, monkeypatch):
    monkeypatch.setattr(updater, "check", lambda: REL)
    ctl.set_choice(OfferDialog.SKIP)
    ctl.available = REL
    ctl.offer()
    assert ctl.win.cfg.skipped_version == "0.3.0"
    ctl._offered.clear()
    ctl.win.show()
    ctl.check()
    wait_for(lambda: not ctl._busy)
    assert len(ctl.offers) == 1  # pulada: só o link no rodapé
    ctl.check(manual=True)  # procurar na mão mostra mesmo assim
    wait_for(lambda: len(ctl.offers) == 2)
    ctl.win.hide()


def test_auto_check_respects_setting_and_errors_are_quiet(ctl, monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "check", lambda: calls.append(1) or REL)
    ctl.win.cfg.check_updates = False
    ctl.check()
    assert not calls and not ctl._busy

    def boom():
        raise UpdateError("sem conexão com o GitHub (ConnectError)")

    monkeypatch.setattr(updater, "check", boom)
    ctl.win.cfg.check_updates = True
    ctl.check()
    wait_for(lambda: not ctl._busy)
    assert ctl.available is None and ctl.win.link == "nunca chamado"


def test_update_now_downloads_and_hands_over(ctl, monkeypatch, tmp_path):
    root = tmp_path / "novo"
    launched = []
    monkeypatch.setattr(updater, "download", lambda rel, progress=None, cancel=None: progress(10, 10) or root)
    monkeypatch.setattr(updater, "launch_finisher", lambda r, target, relaunch_args=None: launched.append(r))
    monkeypatch.setattr(update_dialog.QMessageBox, "information", lambda *a, **k: None)
    ctl.set_choice(OfferDialog.UPDATE)
    ctl.available = REL
    ctl.offer()
    wait_for(lambda: ctl.win.quit_called)
    assert launched == [root]


def test_download_error_keeps_app_open(ctl, monkeypatch):
    warned = []

    def fail(rel, progress=None, cancel=None):
        raise UpdateError("o arquivo baixado não confere (SHA-256 diferente); nada foi trocado")

    monkeypatch.setattr(updater, "download", fail)
    monkeypatch.setattr(update_dialog.QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    ctl.set_choice(OfferDialog.UPDATE)
    ctl.available = REL
    ctl.offer()
    wait_for(lambda: warned)
    assert "não confere" in warned[0] and not ctl.win.quit_called


def test_offer_dialog_builds(app):
    d = OfferDialog(REL, None, "")
    assert d.windowTitle() == "Atualização disponível"
    d2 = OfferDialog(REL, None, "Rodando pelo código-fonte")
    d2._done(OfferDialog.SKIP)
    assert d2.choice == OfferDialog.SKIP
    d.deleteLater()
    d2.deleteLater()
