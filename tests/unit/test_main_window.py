"""Janela principal, resumo do estado e ícone (sem monitorar nada: o motor não é ligado)."""

from __future__ import annotations

import os
import struct
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from musentinel.core import engine as engine_mod  # noqa: E402
from musentinel.core.config import Config  # noqa: E402
from musentinel.core.engine import SlotSnapshot  # noqa: E402
from musentinel.core.events import EventBus  # noqa: E402
from musentinel.core.state_machine import State  # noqa: E402
from musentinel.gui import icons, theme  # noqa: E402
from musentinel.gui.summary import display_name, summarize  # noqa: E402


def snap(slot, name, state, **kw):
    base = dict(since=time.time() - 120, alive=True, pid=100 + slot, size=(1280, 960))
    base.update(kw)
    return SlotSnapshot(slot, name, state, **base)


# ---------------------------------------------------------------- resumo (sem Qt)
def test_display_name_hides_default_slot_name():
    assert display_name(2, "Slot 2") == "Janela 2"
    assert display_name(2, "") == "Janela 2"
    assert display_name(2, "Elfa") == "Elfa"


def test_summary_priorities():
    assert summarize([]).status is None and "Procurando" in summarize([]).text
    ok = [snap(1, "Elfa", State.CACANDO), snap(2, "Slot 2", State.ONLINE)]
    assert summarize(ok).status == "ok" and summarize(ok).text == "Tudo certo · 2 janelas"
    assert summarize(ok[:1]).text == "Tudo certo · 1 janela"
    warn = ok + [snap(3, "Loja", State.PARADO)]
    assert summarize(warn).status == "atencao" and summarize(warn).text == "Atenção: Loja PARADO"
    crit = warn + [snap(4, "Crusader", State.MORTO), snap(5, "Slot 5", State.DESCONECTADO)]
    s = summarize(crit)
    assert s.status == "critico" and s.text == "2 alertas: Crusader MORTO, Janela 5 DESCONECTADO"
    # pausado perde só para alerta crítico
    assert summarize(warn, paused=True, paused_until=float("inf")).text == "Alertas pausados"
    until = time.time() + 3600
    assert summarize(ok, paused=True, paused_until=until).text == \
        f"Alertas pausados até {time.strftime('%H:%M', time.localtime(until))}"
    assert summarize(crit, paused=True).text.endswith("· alertas pausados")


# ---------------------------------------------------------------- ícone
@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a
    for w in QApplication.topLevelWidgets():  # janela viva no fim do Python derruba o processo no Windows
        w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def test_icon_has_transparent_corners_and_status_badge(app):
    brand = icons.draw_brand(32)
    assert brand.pixelColor(0, 0).alpha() == 0  # fundo transparente
    assert brand.pixelColor(16, 16).alpha() == 255  # olho no meio
    for status, color in icons.STATUS_COLOR.items():
        img = icons.draw_status(32, status)
        # centro da bolinha (canto de baixo à direita), fora do símbolo branco
        px = img.pixelColor(31 - 3, 31 - 6)
        assert px.alpha() == 255 and abs(px.red() - QColor(color).red()) < 40, status
    assert icons.draw_status(32, None) == icons.draw_brand(32)


def test_ico_file_has_every_size(app):
    data = icons.ico_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind, count) == (0, 1, len(icons.SIZES))
    for i, sz in enumerate(icons.SIZES):
        w, h, _, _, planes, bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        assert w == (0 if sz == 256 else sz) and planes == 1 and bpp == 32
        assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n" and offset + size <= len(data)


def test_committed_ico_matches_drawing(app):
    from musentinel.core import paths

    ico = paths.app_dir() / "assets" / "musentinel.ico"
    assert ico.read_bytes() == icons.ico_bytes(), "rode: python -m musentinel.tools.make_icon"


# ---------------------------------------------------------------- janela principal
@pytest.fixture
def win(app, monkeypatch):
    from musentinel.gui import update_dialog
    from musentinel.gui.main_window import MainWindow

    monkeypatch.setattr(engine_mod.Engine, "start", lambda self: None)
    monkeypatch.setattr(update_dialog.UpdateController, "start", lambda self: None)
    cfg = Config()
    cfg.wizard_done = True
    cfg.last_seen_version = "0.0.0"
    w = MainWindow(cfg, EventBus(None), start_hidden=True)
    w._pending_notes = ""
    w.show()
    yield w
    w.quit_now()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_window_renders_cards_summary_and_tray(win):
    thumb = np.zeros((240, 320, 3), np.uint8)
    snaps = [
        snap(1, "Elfa", State.CACANDO, hp=(2840, 3100), map="Kanturu", coords=(120, 88), exp_per_h=4.8e7,
             exp_pct_per_h=3.4, hunting_time=5400, connected=True, panels=["caca"], thumb=thumb),
        snap(2, "Loja", State.ONLINE, shop=True, panels=["loja"], shop_status=(12, 32, None), thumb=thumb),
        snap(3, "Crusader", State.MORTO, hp=(0, 4100), connected=False),
    ]
    win.engine.alerts.active[(3, "MORTO")] = object()
    win.on_snapshots(snaps)
    win.refresh_status()
    assert sorted(win.cards) == [1, 2, 3] and win.empty.isHidden()
    assert "1 alerta: Crusader MORTO" in win.summary_lbl.text()
    assert win.tray.toolTip() == "MU Sentinel · 1 alerta: Crusader MORTO"
    assert win.tray_header.text() == "1 alerta: Crusader MORTO"
    assert win.ack_action.isVisible() and "o alerta" in win.ack_btn.text()

    elfa, loja, crus = win.cards[1], win.cards[2], win.cards[3]
    assert elfa.title.text() == "Elfa" and elfa.sub.text() == "janela 1"
    assert elfa.hp_bar.value() == 916 and "2.840 / 3.100" in elfa.hp_text.text()
    assert "48,0 mi" in elfa.row_widgets["exph"][1].text()
    assert elfa.row_widgets["shop"][1].isHidden()
    assert loja.row_widgets["hp"][1].isHidden()  # sem leitura de HP: a linha some
    assert "<b>12/32</b> itens" in loja.row_widgets["shop"][1].text()
    assert not crus.b_ack.isHidden() and crus.property("alerta") is True
    assert elfa.b_ack.isHidden() and elfa.property("alerta") is False
    assert "sem conexão" in crus.row_widgets["conn"][1].text()

    win.engine.alerts.active.clear()
    win.on_snapshots(snaps[:2])
    win.refresh_status()
    assert "Tudo certo · 2 janelas" in win.summary_lbl.text() and not win.ack_action.isVisible()

    win.engine.pause_alerts(None)
    win.refresh_status()
    assert "Alertas pausados" in win.summary_lbl.text() and "Retomar" in win.pause_btn.text()
    assert "retomar" in win.banner.text()
    win.engine.resume_alerts()

    for n in list(win.cards):
        win.remove_card(n)
    win.on_snapshots([])
    assert not win.empty.isHidden() and "Procurando" in win.summary_lbl.text()


def test_theme_stylesheet_has_both_schemes(app):
    css = theme.stylesheet()
    assert "QFrame#card" in css and "QLabel#banner" in css
    assert set(theme.colors()) >= {"card", "border", "muted", "warn_bg", "warn_fg", "link"}
