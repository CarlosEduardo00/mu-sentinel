"""Alertas: intervalo mínimo, agrupamento, repetição, reconhecimento, horário silencioso, pausa."""

import time

from musentinel.core.alerts import Alert, AlertManager, in_quiet_hours
from musentinel.core.config import Config
from musentinel.core.notifiers import FakeNotifier


class Clock:
    def __init__(self, t=None):
        # 12:00 local de um dia qualquer
        self.t = t or time.mktime((2026, 10, 29, 12, 0, 0, 0, 0, -1))

    def __call__(self):
        return self.t

    def advance(self, minutes):
        self.t += minutes * 60


def make(cfg=None, inbound=False):
    clk = Clock()
    ext, local = FakeNotifier(external=True), FakeNotifier(external=False)
    ext.supports_inbound = inbound
    m = AlertManager(cfg or Config(), [local, ext], clock=clk)
    return m, clk, ext, local


def crit(slot=1, kind="MORTO"):
    return Alert(slot, kind, "critico", "MORTE", f'Slot {slot} "Elf" (Kanturu 213,39)', "HP 0/807")


def test_format_matches_spec():
    m, clk, ext, _ = make(inbound=True)
    m.submit(crit(2))
    m.flush()
    lines = ext.sent[0].splitlines()
    assert lines[0] == '[CRÍTICO] MORTE - Slot 2 "Elf" (Kanturu 213,39)'
    assert lines[1] == "12:00 · HP 0/807 · nível 0"
    assert lines[2] == "Responda: print 2 · ok"


def test_no_reply_line_without_inbound():
    m, clk, ext, _ = make()
    m.submit(crit())
    m.flush()
    assert "Responda" not in ext.sent[0]


def test_cooldown_same_alert_same_slot():
    m, clk, ext, _ = make()
    assert m.submit(crit())
    m.flush()
    m.resolve(1)
    clk.advance(2)
    assert not m.submit(crit())  # mesma morte 2 min depois: segurado
    clk.advance(4)
    assert m.submit(crit())
    m.flush()
    assert len(ext.sent) == 2


def test_cooldown_is_per_slot():
    m, clk, ext, _ = make()
    assert m.submit(crit(1))
    assert m.submit(crit(2))


def test_grouping_same_cycle():
    m, clk, ext, _ = make()
    m.submit(crit(1))
    m.submit(crit(2))
    m.submit(Alert(3, "PARADO", "aviso", "CAÇA PARADA"))
    m.flush()
    assert len(ext.sent) == 1
    assert ext.sent[0].startswith("[CRÍTICO] 3 alertas ao mesmo tempo")


def test_critical_repeats_max_3_without_reply():
    m, clk, ext, _ = make()
    m.submit(crit())
    m.flush()
    for _ in range(10):
        clk.advance(5)
        m.flush()
    assert len(ext.sent) == 4  # original + 3 repetições
    assert "(repetição 3)" in ext.sent[-1]


def test_critical_repeats_until_ok_with_inbound():
    m, clk, ext, _ = make(inbound=True)
    m.submit(crit())
    m.flush()
    for _ in range(6):
        clk.advance(5)
        m.flush()
    assert len(ext.sent) == 7
    m.ack()
    clk.advance(5)
    m.flush()
    assert len(ext.sent) == 7


def test_repeat_respects_interval():
    m, clk, ext, _ = make()
    m.submit(crit())
    m.flush()
    clk.advance(4)
    m.flush()
    assert len(ext.sent) == 1


def test_warning_sent_once():
    m, clk, ext, _ = make()
    m.submit(Alert(1, "PARADO", "aviso", "CAÇA PARADA"))
    m.flush()
    for _ in range(5):
        clk.advance(5)
        m.flush()
    assert len(ext.sent) == 1


def test_resolve_stops_repetition():
    m, clk, ext, _ = make()
    m.submit(crit())
    m.flush()
    m.resolve(1)
    clk.advance(5)
    m.flush()
    assert len(ext.sent) == 1


def test_quiet_hours_blocks_external_warnings_but_not_local():
    cfg = Config()
    cfg.alerts.quiet.enabled = True
    cfg.alerts.quiet.start, cfg.alerts.quiet.end = "11:00", "13:00"
    m, clk, ext, local = make(cfg)
    m.submit(Alert(1, "PARADO", "aviso", "CAÇA PARADA"))
    m.flush()
    assert ext.sent == [] and len(local.sent) == 1
    m.submit(crit())
    m.flush()
    assert len(ext.sent) == 1  # crítico passa (padrão)


def test_quiet_hours_can_block_criticals():
    cfg = Config()
    cfg.alerts.quiet.enabled = True
    cfg.alerts.quiet.start, cfg.alerts.quiet.end = "11:00", "13:00"
    cfg.alerts.quiet.allow_critical = False
    m, clk, ext, _ = make(cfg)
    m.submit(crit())
    m.flush()
    assert ext.sent == []


def test_quiet_hours_over_midnight():
    cfg = Config()
    cfg.alerts.quiet.enabled = True
    cfg.alerts.quiet.start, cfg.alerts.quiet.end = "23:00", "07:00"
    at = lambda h: time.mktime((2026, 10, 29, h, 30, 0, 0, 0, -1))  # noqa: E731
    assert in_quiet_hours(cfg, at(23)) and in_quiet_hours(cfg, at(3))
    assert not in_quiet_hours(cfg, at(7)) and not in_quiet_hours(cfg, at(12))


def test_pause_and_resume():
    m, clk, ext, local = make()
    m.pause(30)
    m.submit(crit())
    m.flush()
    assert ext.sent == [] and local.sent == []
    clk.advance(31)
    assert not m.paused
    m.pause()
    assert m.paused
    m.resume()
    assert not m.paused


def test_failing_notifier_does_not_block_others():
    m, clk, ext, local = make()

    class Boom(FakeNotifier):
        def send(self, text, image=None):
            raise RuntimeError("caiu")

    m.set_notifiers([Boom(), ext])
    m.submit(crit())
    m.flush()
    assert len(ext.sent) == 1
