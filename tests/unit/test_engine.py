"""Motor do monitor de ponta a ponta, com janelas, captura e leitura falsas."""

import numpy as np
import pytest

from musentinel.core import engine as engine_mod
from musentinel.core import health
from musentinel.core.capture.base import Frame
from musentinel.core.config import Config
from musentinel.core.discovery import Discovery
from musentinel.core.events import EventBus
from musentinel.core.notifiers import FakeNotifier
from musentinel.core.state_machine import State
from musentinel.core.winapi import WindowInfo

SRV = ("139.5.226.147", 55901)


class Game:
    """Estado falso de N clients."""

    def __init__(self, n):
        self.alive = {i: True for i in range(1, n + 1)}
        self.conn = {i: True for i in range(1, n + 1)}
        self.hp = {i: (800, 811) for i in range(1, n + 1)}
        self.map = {i: "Kanturu" for i in range(1, n + 1)}
        self.exp = {i: 100_000 for i in range(1, n + 1)}
        self.frame_n = 0

    def windows(self):
        return [WindowInfo(i, 1000 + i, "MU", "main.exe", (800, 600), False, False)
                for i, a in self.alive.items() if a]


class FakeCapture:
    def __init__(self, game):
        self.game = game

    def grab(self, hwnd):
        self.game.frame_n += 1
        img = np.full((600, 800, 3), (self.game.frame_n * 37) % 255, np.uint8)  # sempre muda
        img[0, 0, 0] = hwnd
        return Frame(img, hwnd, "fake")

    def close(self):
        pass


class FakeReading:
    def __init__(self, vals):
        self.vals = vals

    def value(self, name, min_conf=0.0):
        return self.vals.get(name)


class FakeReader:
    def __init__(self, game):
        self.game = game

    def read(self, img):
        i = int(img[0, 0, 0])
        g = self.game
        g.exp[i] += 300
        return FakeReading({"hp": g.hp[i], "exp": (g.exp[i], 2_000_000), "map": g.map[i], "coords": (213, 39),
                            "hunting_time": None})


@pytest.fixture
def rig(monkeypatch):
    def make(n=2):
        game = Game(n)
        monkeypatch.setattr(health, "tcp_by_pid", lambda: {1000 + i: {SRV} for i, c in game.conn.items() if c})
        monkeypatch.setattr(health, "process_alive", lambda pid, name=None: game.alive.get(pid - 1000, False))
        monkeypatch.setattr(health, "window_hung", lambda hwnd: False)
        monkeypatch.setattr(health, "session_locked", lambda: False)
        monkeypatch.setattr(health, "user_idle_s", lambda: 9999)
        monkeypatch.setattr(health, "internet_ok", lambda timeout=2.0: True)
        clock = {"t": 1_000_000.0}
        monkeypatch.setattr(engine_mod.time, "time", lambda: clock["t"])
        cfg = Config()
        cfg.alerts.cooldown_min = 0
        ext = FakeNotifier(external=True)
        bus = EventBus()
        e = engine_mod.Engine(cfg, bus, [ext])
        e.discovery = Discovery(lister=game.windows, rect_of=lambda w: (w.hwnd * 900, 0, 800, 600), store=None)
        e._capture = FakeCapture(game)
        e._readers[(800, 600)] = FakeReader(game)
        e.internet.ok = True

        def run(cycles):
            for _ in range(cycles):
                clock["t"] += cfg.monitor.interval_s
                e.cycle()

        return game, e, ext, run, clock

    return make


def test_death_alert_within_30s(rig):
    game, e, ext, run, clock = rig(1)
    run(5)
    assert e.slots[1].tracker.view.state == State.CACANDO
    t0 = clock["t"]
    game.hp[1] = (0, 811)
    for _ in range(15):
        run(1)
        if ext.sent:
            break
    assert ext.sent, "morte não alertada"
    assert clock["t"] - t0 <= 30
    assert ext.sent[0].startswith('[CRÍTICO] MORTE - Slot 1 "Slot 1" (Kanturu 213,39)')


def test_single_disconnect_alert(rig):
    game, e, ext, run, clock = rig(2)
    run(5)
    t0 = clock["t"]
    game.conn[2] = False
    run(4)
    assert len(ext.sent) == 1 and "DESCONECTADO - Slot 2" in ext.sent[0]
    assert clock["t"] - t0 <= 30
    game.conn[2] = True
    run(4)
    assert "RESOLVIDO" in ext.sent[-1]


def test_general_outage_single_message(rig, monkeypatch):
    game, e, ext, run, clock = rig(3)
    run(5)
    for i in game.conn:
        game.conn[i] = False
    monkeypatch.setattr(health, "internet_ok", lambda timeout=2.0: False)
    run(4)
    assert len(ext.sent) == 1
    assert "TODOS OS SLOTS CAÍRAM" in ext.sent[0] and "internet deste PC fora do ar" in ext.sent[0]


def test_internet_probe_down_marks_disconnect_fast(rig):
    game, e, ext, run, clock = rig(2)
    run(5)
    e.internet.ok = False  # o socket do jogo ainda parece ESTABLISHED
    run(3)
    assert len(ext.sent) == 1 and "SLOTS CAÍRAM" in ext.sent[0]


def test_client_closed(rig):
    game, e, ext, run, clock = rig(2)
    run(5)
    game.alive[1] = False
    run(3)
    assert any("CLIENT FECHADO - Slot 1" in m for m in ext.sent)
    assert e.slots[1].tracker.view.state == State.FECHADO
    assert e.slots[2].tracker.view.state == State.CACANDO


def test_reopened_client_same_slot_resolves(rig):
    game, e, ext, run, clock = rig(1)
    run(5)
    game.alive[1] = False
    run(3)
    game.alive[1] = True  # mesmo hwnd/pid falsos: simula reabertura no mesmo lugar
    run(5)
    assert e.slots[1].tracker.view.state in (State.ONLINE, State.CACANDO)
    assert "RESOLVIDO" in ext.sent[-1]


def test_snapshots_published(rig):
    game, e, ext, run, clock = rig(2)
    got = []
    e.bus.subscribe("snapshots", got.append)
    run(3)
    snaps = got[-1]
    assert [s.slot for s in snaps] == [1, 2]
    assert snaps[0].hp == (800, 811) and snaps[0].map == "Kanturu" and snaps[0].thumb is not None
