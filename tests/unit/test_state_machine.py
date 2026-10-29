"""Máquina de estados com sequências sintéticas, incluindo as armadilhas
(menu aberto, janela coberta, loading, lag)."""

from musentinel.core.config import Config
from musentinel.core.state_machine import ExpRate, Observation, SlotTracker, State

CYCLE = 2.0


class Sim:
    """Gera observações de um personagem caçando, ciclo a ciclo."""

    def __init__(self, cfg=None):
        self.cfg = cfg or Config()
        self.t = 1_000_000.0
        self.tr = SlotTracker(1, self.cfg)
        self.exp = 100_000
        self.ht = 0
        self.signals = []

    def step(self, n=1, gain=True, **kw):
        out = []
        for _ in range(n):
            self.t += CYCLE
            if gain:
                self.exp += 500
                self.ht += 2
            base = dict(ts=self.t, hp=(800, 811), exp=(self.exp, 2_000_000), coords=(213, 39),
                        map="Kanturu", hunting_time=self.ht, connected=True)
            base.update(kw)
            sig = self.tr.update(Observation(**base))
            out += sig
            self.signals += sig
        return out

    @property
    def state(self):
        return self.tr.view.state

    def kinds(self, sigs=None):
        return [s.kind for s in (self.signals if sigs is None else sigs)]


def hunting():
    s = Sim()
    s.step(5)
    assert s.state == State.CACANDO
    s.signals.clear()
    return s


def test_starts_online_then_hunting():
    s = Sim()
    s.step(1)
    assert s.state == State.ONLINE
    s.step(3)
    assert s.state == State.CACANDO
    assert s.kinds() == []  # entrar em caça não alerta


def test_death_by_hp_zero_is_critical_and_latched():
    s = hunting()
    s.step(4, gain=False, hp=(0, 811))
    assert s.state == State.MORTO
    assert s.kinds() == ["MORTO"]
    sig = s.signals[0]
    assert sig.severity == "critico" and "HP 0/811" in sig.detail and "CAÇANDO" in sig.detail
    # renasce na cidade com HP cheio: continua MORTO (não "resolve" sozinho)
    s.step(10, gain=False, hp=(811, 811), map="Lorencia")
    assert s.state == State.MORTO
    assert "RESOLVIDO" not in s.kinds()


def test_death_clears_when_exp_rises_again():
    s = hunting()
    s.step(4, gain=False, hp=(0, 811))
    s.step(3, gain=False, hp=(811, 811), map="Lorencia")
    s.step(4, map="Kanturu")  # voltou ao spot e está ganhando EXP
    assert s.state == State.CACANDO
    assert s.kinds()[-1] == "RESOLVIDO"


def test_single_hp_zero_misread_is_not_death():
    s = hunting()
    s.step(1, hp=(0, 811))
    s.step(5)
    assert s.state == State.CACANDO
    assert s.kinds() == []


def test_city_after_hunting_without_user_is_death():
    s = hunting()
    s.step(4, gain=False, hp=(811, 811), map="Lorencia")
    assert s.state == State.MORTO
    assert "Kanturu para Lorencia" in s.signals[0].detail


def test_city_trip_by_user_is_not_death():
    s = hunting()
    s.step(4, gain=False, hp=(811, 811), map="Lorencia", user_active=True)
    assert s.state != State.MORTO
    assert "MORTO" not in s.kinds()


def test_menu_open_trap_unreadable_never_critical():
    s = hunting()
    # menu por cima do HUD: nada legível por 3 minutos
    s.step(90, gain=False, hp=None, exp=None, map=None, coords=None, hunting_time=None)
    assert s.state == State.ILEGIVEL
    assert all(x.severity != "critico" for x in s.signals)
    assert s.kinds() == ["ILEGIVEL"]  # um aviso só, depois de 2 min
    s.step(4)
    assert s.state == State.CACANDO


def test_short_loading_does_not_alert():
    s = hunting()
    s.step(5, gain=False, hp=None, exp=None, map=None, hunting_time=None)  # 10 s de loading
    s.step(4)
    assert s.kinds() == []


def test_lag_single_glitch_cycle_needs_confirmation():
    s = hunting()
    s.step(1, connected=False)  # 1 ciclo de leitura estranha
    s.step(3)
    assert s.state == State.CACANDO
    assert s.kinds() == []


def test_disconnect():
    s = hunting()
    s.step(3, gain=False, connected=False)
    assert s.state == State.DESCONECTADO
    assert s.kinds() == ["DESCONECTADO"]


def test_process_closed():
    s = hunting()
    s.step(2, gain=False, process_alive=False, capture_ok=False, hp=None, exp=None)
    assert s.state == State.FECHADO
    assert s.kinds() == ["FECHADO"]


def test_hung_window_needs_10s():
    s = hunting()
    s.step(3, gain=False, hung=True)  # 6 s
    assert s.state == State.CACANDO
    s.step(5, gain=False, hung=True)
    assert s.state == State.TRAVADO


def test_frozen_frame_but_not_when_locked():
    s = hunting()
    s.step(3, gain=False, frame_static_s=40, locked=True)
    assert s.state != State.TRAVADO
    s.step(3, gain=False, frame_static_s=40)
    assert s.state == State.TRAVADO


def test_exp_stall_becomes_parado_with_warning():
    s = hunting()
    s.step(160, gain=False)  # 5 min 20 s sem EXP
    assert s.state == State.PARADO
    assert "PARADO" in s.kinds()
    assert all(x.severity != "critico" for x in s.signals)


def test_parado_even_if_hunting_time_keeps_counting():
    s = hunting()
    for _ in range(160):
        s.ht += 2
        s.step(1, gain=False, hunting_time=s.ht)
    assert s.state == State.PARADO


def test_helper_stopped_warning_once():
    s = hunting()
    s.step(25, gain=False)  # Hunting Time parado por 50 s, ainda dentro dos 5 min de EXP
    assert s.kinds().count("HELPER") == 1


def test_hp_low_warning_once_and_rearms():
    s = hunting()
    s.step(3, hp=(200, 811))
    s.step(3, hp=(150, 811))
    assert s.kinds().count("HP_BAIXO") == 1
    s.step(3, hp=(811, 811))
    s.step(3, hp=(100, 811))
    assert s.kinds().count("HP_BAIXO") == 2


def test_idle_in_town_from_start_never_alerts_parado():
    s = Sim()
    s.step(200, gain=False, map="Lorencia")
    assert s.state == State.PARADO
    assert s.kinds() == []  # nunca caçou: não é "caça parada"


def test_confirm_cycles_configurable():
    cfg = Config()
    cfg.monitor.confirm_cycles = 3
    s = Sim(cfg)
    s.step(5)
    s.step(2, gain=False, connected=False)
    assert s.state == State.CACANDO
    s.step(1, gain=False, connected=False)
    assert s.state == State.DESCONECTADO


def test_reconnect_resolves():
    s = hunting()
    s.step(3, gain=False, connected=False)
    s.step(4)
    assert s.state == State.CACANDO
    assert s.kinds() == ["DESCONECTADO", "RESOLVIDO"]


def test_exp_rate_with_level_up():
    r = ExpRate()
    r.add(0, 900, 1000)
    r.add(60, 1000, 1000)
    r.add(120, 50, 2000)  # subiu de nível: +0 para fechar o nível + 50 no novo
    per_h, pct_h = r.rate(120)
    assert round(per_h) == round((100 + 50) * 3600 / 120)
    assert pct_h > 0
