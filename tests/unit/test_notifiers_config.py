"""CallMeBot (com HTTP falso), configuração, logs mascarados e descoberta de janelas."""

import logging
from urllib.parse import parse_qs, urlparse

import pytest

from musentinel.core.config import Config, WhatsAppRecipient, mask_phone
from musentinel.core.discovery import Discovery
from musentinel.core.health import ConnectionTracker, FrameWatcher
from musentinel.core.logsetup import ScrubFilter, scrub
from musentinel.core.notifiers.callmebot import CallMeBotNotifier, build_url, classify
from musentinel.core.winapi import WindowInfo

OK_BODY = "<p><b>Message queued</b>. You will receive it in a few seconds.</p>"
BAD_KEY = "<p>APIKey is invalid. You need to get the apikey first</p>"
KEYS = {"callmebot:5511999990001": "111111", "callmebot:5521988880002": "222222"}


class FakeHttp:
    def __init__(self, responses=None):
        self.urls = []
        self.responses = list(responses or [])

    def __call__(self, url, timeout):
        self.urls.append(url)
        r = self.responses.pop(0) if self.responses else (200, OK_BODY)
        if isinstance(r, Exception):
            raise r
        return r


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def recips():
    return [WhatsAppRecipient(nome="Eu", telefone="+55 (11) 99999-0001"),
            WhatsAppRecipient(nome="Amigo", telefone="55 21 98888-0002")]


def notifier(http, clock):
    return CallMeBotNotifier(recips(), 5, http_get=http, key_lookup=KEYS.get, clock=clock,
                             sleep=clock.sleep, start=False)


def drain(n: CallMeBotNotifier, clock, max_steps=200):
    for _ in range(max_steps):
        job = n._next_job()
        if job is None:
            if not n._retry:
                return
            clock.t = min(j.not_before for j in n._retry)
            continue
        wait = max(0.0, n._last_send + n.min_interval_s - clock())
        clock.sleep(wait)
        n._deliver(job)


def test_each_recipient_gets_message_with_own_key():
    http, clk = FakeHttp(), Clock()
    n = notifier(http, clk)
    n.send("[CRÍTICO] MORTE - Slot 1 · HP 0/807")
    drain(n, clk)
    assert len(http.urls) == 2
    q = [parse_qs(urlparse(u).query) for u in http.urls]
    assert q[0]["phone"] == ["+5511999990001"] and q[0]["apikey"] == ["111111"]
    assert q[1]["phone"] == ["+5521988880002"] and q[1]["apikey"] == ["222222"]
    assert q[0]["text"] == ["[CRÍTICO] MORTE - Slot 1 · HP 0/807"]


def test_min_interval_between_sends():
    http, clk = FakeHttp(), Clock()
    n = notifier(http, clk)
    t0 = clk()
    n.send("a")
    n.send("b")
    drain(n, clk)
    assert len(http.urls) == 4
    assert clk() - t0 >= 15  # 4 envios, 5 s entre eles


def test_retry_with_backoff_then_success():
    http, clk = FakeHttp([OSError("sem rede"), (502, "bad gateway"), (200, OK_BODY)]), Clock()
    n = CallMeBotNotifier(recips()[:1], 5, http_get=http, key_lookup=KEYS.get, clock=clk, sleep=clk.sleep,
                          start=False)
    n.send("x")
    drain(n, clk)
    assert len(http.urls) == 3
    assert n.status().ok


def test_invalid_key_is_not_retried_and_status_explains():
    http, clk = FakeHttp([(200, BAD_KEY)]), Clock()
    n = CallMeBotNotifier(recips()[:1], 5, http_get=http, key_lookup=KEYS.get, clock=clk, sleep=clk.sleep,
                          start=False)
    n.send("x")
    drain(n, clk)
    assert len(http.urls) == 1
    st = n.status()
    assert not st.ok and "recusados" in st.detail
    assert "111111" not in st.detail


def test_missing_key_skips_without_request():
    http, clk = FakeHttp(), Clock()
    n = CallMeBotNotifier(recips()[:1], 5, http_get=http, key_lookup=lambda k: None, clock=clk,
                          sleep=clk.sleep, start=False)
    n.send("x")
    drain(n, clk)
    assert http.urls == [] and not n.status().ok


def test_send_now_errors_never_contain_key():
    def boom(url, timeout):
        raise OSError(f"falhou {url}")

    n = CallMeBotNotifier(recips(), http_get=boom, key_lookup=KEYS.get, start=False)
    ok, msg = n.send_now(recips()[0], "teste")
    assert not ok and "111111" not in msg and "apikey" not in msg.lower()


def test_classify():
    assert classify(200, OK_BODY) == "ok"
    assert classify(200, BAD_KEY) == "fatal"
    assert classify(500, "") == "retry"


def test_url_encoding():
    u = build_url("5511999990001", "a & b · ç\nlinha 2", "k&y")
    q = parse_qs(urlparse(u).query)
    assert q["text"] == ["a & b · ç\nlinha 2"] and q["apikey"] == ["k&y"]


# ---------------------------------------------------------------- config
def test_config_yaml_roundtrip_portuguese_keys_and_no_secrets():
    c = Config()
    c.notifiers.callmebot.enabled = True
    c.notifiers.callmebot.recipients = recips()
    c.slot(2).name = "Elf Kanturu"
    y = c.to_yaml()
    assert "destinatarios:" in y and "telefone: '5511999990001'" in y and "nome: Elf Kanturu" in y
    assert "111111" not in y and "apikey" not in y.lower()
    c2 = Config.from_yaml(y)
    assert c2.notifiers.callmebot.recipients[1].phone == "5521988880002"
    assert c2.slot_name(2) == "Elf Kanturu" and c2.slot_name(3) == "Slot 3"
    assert c2.level == 0


def test_config_defaults_and_validation():
    c = Config()
    assert c.level == 0 and c.monitor.interval_s == 2 and c.is_city("lorencia")
    with pytest.raises(ValueError):
        WhatsAppRecipient(telefone="123")


def test_config_newer_version_rejected():
    with pytest.raises(ValueError, match="versão 99"):
        Config.from_yaml("versao: 99\n")


def test_config_save_load(tmp_path):
    p = tmp_path / "config.yaml"
    c = Config()
    c.cities = ["Lorencia", "Kalima"]
    c.save(p)
    assert Config.load(p).cities == ["Lorencia", "Kalima"]


# ---------------------------------------------------------------- logs
def test_scrub_masks_phones_and_secrets():
    s = scrub("enviando para +55 11 99999-0001 url ...&apikey=123456&x=1 token=abc")
    assert "99999-0001" not in s and "0001" in s
    assert "123456" not in s and "abc" not in s
    assert scrub("HP 805/811 coords 212,32 EXP 1140017/1837420") == "HP 805/811 coords 212,32 EXP 1140017/1837420"
    assert mask_phone("5511999990001") == "+55•••••••0001"


def test_log_filter(caplog):
    lg = logging.getLogger("teste.mask")
    lg.addFilter(ScrubFilter())
    with caplog.at_level(logging.INFO):
        lg.info("tel %s chave apikey=%s", "5511999990001", "SEGREDO")
    assert "SEGREDO" not in caplog.text and "5511999990001" not in caplog.text


# ---------------------------------------------------------------- descoberta e saúde
def win(hwnd, pid):
    return WindowInfo(hwnd, pid, "MU", "main.exe", (1280, 960), False, True)


def test_discovery_reopened_client_keeps_slot(tmp_path):
    wins = [win(1, 100), win(2, 200)]
    rects = {1: (0, 0, 1296, 999), 2: (1300, 0, 1296, 999), 3: (1302, 4, 1296, 999)}
    d = Discovery(lister=lambda: wins, rect_of=lambda w: rects[w.hwnd], store=tmp_path / "s.json")
    m = d.refresh()
    assert {s: b.pid for s, b in m.items()} == {1: 100, 2: 200}
    wins[:] = [win(1, 100)]  # client do slot 2 fechou
    assert set(d.refresh()) == {1}
    wins[:] = [win(1, 100), win(3, 300)]  # reabriu quase no mesmo lugar
    m = d.refresh()
    assert m[2].pid == 300
    # persistência: nova execução do app reaproveita o número pelo lugar
    d2 = Discovery(lister=lambda: [win(3, 300)], rect_of=lambda w: rects[w.hwnd], store=tmp_path / "s.json")
    assert d2.refresh()[2].pid == 300


def test_discovery_new_window_gets_next_free_slot(tmp_path):
    wins = [win(1, 100)]
    rects = {1: (0, 0, 800, 600), 2: (900, 0, 800, 600)}
    d = Discovery(lister=lambda: wins, rect_of=lambda w: rects[w.hwnd], store=None)
    d.refresh()
    wins.append(win(2, 200))
    assert d.refresh()[2].pid == 200


def test_connection_tracker():
    t = ConnectionTracker()
    srv = {("139.5.226.147", 55901)}
    assert t.update(set(), False) is None  # sem referência: desconhecido
    assert t.update(srv, True) is True
    assert t.update(srv, False) is True
    assert t.update(set(), False) is False  # referência sumiu: desconectado
    new = {("139.5.226.150", 55902)}
    assert t.update(new, True) is True  # trocou de servidor com o jogo online
    assert t.reference == new


def test_frame_watcher():
    import numpy as np

    fw = FrameWatcher()
    a = np.zeros((96, 128, 3), np.uint8)
    b = a.copy()
    b[:40] = 200
    assert fw.update(a, 0) == 0
    assert fw.update(a, 10) == 10
    assert fw.update(b, 12) == 0


def test_discovery_remembered_slots_do_not_block_numbers(tmp_path):
    store = tmp_path / "s.json"
    rects = {1: (0, 0, 800, 600), 2: (900, 0, 800, 600), 7: (0, 700, 800, 600), 8: (900, 700, 800, 600)}
    d = Discovery(lister=lambda: [win(1, 100), win(2, 200)], rect_of=lambda w: rects[w.hwnd], store=store)
    d.refresh()
    # nova execução, janelas em outros lugares: continuam 1 e 2 (não viram 3 e 4)
    d2 = Discovery(lister=lambda: [win(7, 700), win(8, 800)], rect_of=lambda w: rects[w.hwnd], store=store)
    assert sorted(d2.refresh()) == [1, 2]


def test_discovery_closed_slot_reserved_in_same_session(tmp_path):
    rects = {1: (0, 0, 800, 600), 2: (900, 0, 800, 600), 3: (0, 700, 800, 600)}
    wins = [win(1, 100), win(2, 200)]
    d = Discovery(lister=lambda: wins, rect_of=lambda w: rects[w.hwnd], store=None)
    d.refresh()
    wins[:] = [win(2, 200)]
    d.refresh()  # slot 1 fechou (fica FECHADO no painel)
    wins.append(win(3, 300))  # outra janela abriu em outro lugar: não rouba o slot 1
    assert d.refresh()[3].pid == 300


def test_discovery_owner_hidden_keeps_same_slot(tmp_path):
    rects = {1: (0, 0, 800, 600), 2: (900, 0, 800, 600)}
    wins = [win(1, 100), win(2, 200)]
    d = Discovery(lister=lambda: wins, rect_of=lambda w: rects[w.hwnd], store=None)
    d.refresh()
    wins[:] = [win(1, 0), win(2, 0)]  # anti-cheat passou a esconder o processo dono
    m = d.refresh()
    assert {s: (b.hwnd, b.pid) for s, b in m.items()} == {1: (1, 0), 2: (2, 0)}
    wins[:] = [win(1, 100), win(2, 200)]  # voltou a mostrar
    m = d.refresh()
    assert {s: b.pid for s, b in m.items()} == {1: 100, 2: 200}
