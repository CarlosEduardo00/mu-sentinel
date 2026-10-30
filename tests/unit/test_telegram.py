"""Telegram com HTTP falso: envio, foto, erros, nova tentativa, busca de conversas e sigilo do token."""

from musentinel.core.alerts import Alert, AlertManager
from musentinel.core.config import TELEGRAM_TOKEN_KEY, Config, TelegramChat
from musentinel.core.notifiers import FakeNotifier
from musentinel.core.notifiers.telegram import TelegramApi, TelegramNotifier, send_test

TOKEN = "1234567890:TESTE_token_falso_nao_e_de_verdade_00"
OK = (200, {"ok": True, "result": {}})


class FakePost:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def __call__(self, url, data, files):
        self.calls.append((url, dict(data), files))
        r = self.responses.pop(0) if self.responses else OK
        if isinstance(r, Exception):
            raise r
        return r

    def methods(self):
        return [u.rsplit("/", 1)[1] for u, _, _ in self.calls]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def chats():
    return [TelegramChat(nome="Eu", id=111), TelegramChat(nome="Amigo", id=222)]


def notifier(post, clock, token=TOKEN, cs=None):
    return TelegramNotifier(cs or chats(), 1.0, True, http_post=post,
                            token_lookup=lambda k: token if k == TELEGRAM_TOKEN_KEY else None,
                            clock=clock, sleep=clock.sleep, start=False)


def drain(n, clock, steps=100):
    for _ in range(steps):
        job = n._next_job()
        if job is None:
            if not n._retry:
                return
            clock.t = min(j.not_before for j in n._retry)
            continue
        clock.sleep(max(0.0, n._last_send + n.min_interval_s - clock()))
        n._deliver(job)


def test_sends_text_to_each_chat():
    post, clk = FakePost(), Clock()
    n = notifier(post, clk)
    n.send("[CRÍTICO] MORTE - Slot 1")
    drain(n, clk)
    assert post.methods() == ["sendMessage", "sendMessage"]
    assert [d["chat_id"] for _, d, _ in post.calls] == ["111", "222"]
    assert post.calls[0][1]["text"] == "[CRÍTICO] MORTE - Slot 1"
    assert post.calls[0][0] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert n.status().ok


def test_image_goes_as_photo_with_caption():
    post, clk = FakePost(), Clock()
    n = notifier(post, clk, cs=[TelegramChat(id=111)])
    n.send("legenda", b"\xff\xd8jpeg")
    drain(n, clk)
    url, data, files = post.calls[0]
    assert url.endswith("/sendPhoto") and data["caption"] == "legenda"
    assert files["photo"][1] == b"\xff\xd8jpeg"


def test_rate_limit_waits_retry_after():
    post, clk = FakePost([(429, {"ok": False, "error_code": 429, "description": "Too Many Requests",
                                 "parameters": {"retry_after": 7}}), OK]), Clock()
    n = notifier(post, clk, cs=[TelegramChat(id=111)])
    n.send("x")
    t0 = clk()
    drain(n, clk)
    assert len(post.calls) == 2 and clk() - t0 >= 7 and n.status().ok


def test_network_error_retries_and_hides_token():
    post, clk = FakePost([OSError(f"falhou https://api.telegram.org/bot{TOKEN}/sendMessage"), OK]), Clock()
    n = notifier(post, clk, cs=[TelegramChat(id=111)])
    n.send("x")
    job = n._next_job()
    n._deliver(job)
    st = n.status()
    assert not st.ok and TOKEN not in st.detail and "OSError" in st.detail
    drain(n, clk)
    assert len(post.calls) == 2 and n.status().ok


def test_invalid_token_not_retried():
    post, clk = FakePost([(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})]), Clock()
    n = notifier(post, clk, cs=[TelegramChat(id=111)])
    n.send("x")
    drain(n, clk)
    assert len(post.calls) == 1
    assert "token" in n.status().detail and TOKEN not in n.status().detail


def test_blocked_chat_reported_by_name():
    post, clk = FakePost([(403, {"ok": False, "error_code": 403,
                                 "description": "Forbidden: bot was blocked by the user"}), OK]), Clock()
    n = notifier(post, clk)
    n.send("x")
    drain(n, clk)
    assert len(post.calls) == 2  # o outro chat recebeu
    assert "Eu" in n.status().detail and "bloqueou" in n.status().detail


def test_missing_token_sends_nothing():
    post, clk = FakePost(), Clock()
    n = notifier(post, clk, token=None)
    n.send("x")
    drain(n, clk)
    assert post.calls == [] and not n.status().ok


def test_find_chats_from_updates():
    updates = [
        {"update_id": 1, "message": {"chat": {"id": 111, "type": "private", "first_name": "Ana",
                                              "username": "ana"}, "text": "/start"}},
        {"update_id": 2, "message": {"chat": {"id": 111, "type": "private", "first_name": "Ana"}, "text": "oi"}},
        {"update_id": 3, "message": {"chat": {"id": -555, "type": "group", "title": "Guilda"}, "text": "/start"}},
    ]
    api = TelegramApi(TOKEN, FakePost([(200, {"ok": True, "result": updates})]))
    assert dict(api.find_chats()) == {111: "Ana", -555: "Guilda"}


def test_send_test_messages():
    ok, msg = send_test(TOKEN, 111, "teste", FakePost())
    assert ok
    ok, msg = send_test(TOKEN, 111, "teste", FakePost([(400, {"ok": False, "error_code": 400,
                                                              "description": "Bad Request: chat not found"})]))
    assert not ok and "Iniciar" in msg and TOKEN not in msg


def test_alert_image_only_for_image_notifiers():
    plain, pic = FakeNotifier(), FakeNotifier()
    pic.supports_images = True
    m = AlertManager(Config(), [plain, pic])
    m.submit(Alert(1, "MORTO", "critico", "MORTE", image=b"jpg"))
    m.flush()
    assert plain.images == [None] and pic.images == [b"jpg"]


def test_config_roundtrip_has_no_token():
    c = Config()
    c.notifiers.telegram.enabled = True
    c.notifiers.telegram.chats = chats()
    y = c.to_yaml()
    assert "conversas:" in y and "id: 111" in y and TOKEN not in y
    assert Config.from_yaml(y).notifiers.telegram.chats[1].chat_id == 222


# ---------------------------------------------------------------------- pedidos pelo Telegram
def _upd(uid, chat_id, text, date, name="Ana"):
    return {"update_id": uid, "message": {"chat": {"id": chat_id, "type": "private", "first_name": name},
                                          "text": text, "date": date}}


def _listener(post, handler, clock, allowed=(111,)):
    from musentinel.core.notifiers.telegram import TelegramCommandListener

    return TelegramCommandListener(set(allowed), handler, [["📊 Status"]], http_post=post,
                                   token_lookup=lambda k: TOKEN if k == TELEGRAM_TOKEN_KEY else None,
                                   clock=clock, start=False)


def test_listener_answers_only_listed_chats():
    from musentinel.core.notifiers.telegram import NOT_ALLOWED_TEXT, TelegramApi

    clk = Clock()
    asked = []

    def handler(text, chat_id):
        asked.append(text)
        return [("legenda", b"\xff\xd8jpg"), ("texto", None)]

    updates = [_upd(5, 111, "/inventario 2", clk()), _upd(6, 999, "/start", clk(), "Estranho"),
               _upd(7, 999, "/print", clk(), "Estranho"), _upd(8, 999, "/start", clk(), "Estranho")]
    post = FakePost([(200, {"ok": True, "result": updates})])
    lst = _listener(post, handler, clk)
    served = lst.poll_once(TelegramApi(TOKEN, post))
    assert served == 1 and asked == ["/inventario 2"]  # o 999 não está na lista
    sent = [(u.rsplit("/", 1)[1], d) for u, d, _ in post.calls[1:]]
    assert [m for m, _ in sent] == ["sendPhoto", "sendMessage", "sendMessage"]
    assert sent[0][1]["chat_id"] == "111" and "reply_markup" not in sent[0][1]
    assert sent[1][1]["text"] == "texto" and "Status" in sent[1][1]["reply_markup"]  # teclado na última resposta
    assert sent[2][1]["chat_id"] == "999" and sent[2][1]["text"] == NOT_ALLOWED_TEXT  # saudação só uma vez
    assert lst._offset == 9


def test_listener_skips_old_messages_and_keeps_offset():
    from musentinel.core.notifiers.telegram import TelegramApi

    clk = Clock()
    post = FakePost([(200, {"ok": True, "result": [_upd(40, 111, "/status", clk() - 3600)]})])
    lst = _listener(post, lambda t, c: [("x", None)], clk)
    assert lst.poll_once(TelegramApi(TOKEN, post)) == 0 and lst._offset == 41
    post.responses = [(200, {"ok": True, "result": []})]
    lst.poll_once(TelegramApi(TOKEN, post))
    assert post.calls[-1][1]["offset"] == 41


def test_listener_handler_error_still_replies():
    from musentinel.core.notifiers.telegram import TelegramApi

    clk = Clock()

    def boom(text, chat_id):
        raise RuntimeError("falhou")

    post = FakePost([(200, {"ok": True, "result": [_upd(1, 111, "/status", clk())]})])
    _listener(post, boom, clk).poll_once(TelegramApi(TOKEN, post))
    assert "Não consegui" in post.calls[-1][1]["text"]


def test_find_chats_uses_listener_memory_while_running():
    from musentinel.core.notifiers import telegram as tg

    clk = Clock()
    post = FakePost([(200, {"ok": True, "result": [_upd(1, 333, "/start", clk(), "Amigo")]})])
    lst = _listener(post, lambda t, c: [], clk)
    lst._mark(True)
    try:
        lst.poll_once(tg.TelegramApi(TOKEN, post))
        calls = len(post.calls)
        found = dict(tg.TelegramApi(TOKEN, post).find_chats())
        assert found.get(333) == "Amigo" and len(post.calls) == calls  # não chamou getUpdates de novo
    finally:
        lst.close()
    assert not tg.listener_running()


def test_conflict_409_is_explained():
    from musentinel.core.notifiers.telegram import TelegramApi, TelegramError

    post = FakePost([(409, {"ok": False, "error_code": 409, "description": "Conflict: terminated by other getUpdates"})])
    try:
        TelegramApi(TOKEN, post).get_updates()
    except TelegramError as exc:
        assert exc.kind == "retry" and "outra cópia" in exc.description
    else:
        raise AssertionError("esperava erro")


def test_listener_button_updates_message():
    from musentinel.core.notifiers.telegram import TelegramApi, TelegramCommandListener

    clk = Clock()
    seen = []

    def on_button(data, chat_id):
        seen.append((data, chat_id))
        return "Agora: 2 · Elf", ("🎯 Agora: 2 · Elf", [[("✓ 2 · Elf", "alvo:2")]])

    cq = {"update_id": 9, "callback_query": {"id": "cb1", "data": "alvo:2",
                                             "message": {"message_id": 77, "chat": {"id": 111}}}}
    stranger = {"update_id": 10, "callback_query": {"id": "cb2", "data": "alvo:1",
                                                    "message": {"message_id": 5, "chat": {"id": 999}}}}
    post = FakePost([(200, {"ok": True, "result": [cq, stranger]})])
    lst = TelegramCommandListener({111}, lambda t, c: [], http_post=post, on_button=on_button,
                                  token_lookup=lambda k: TOKEN, clock=clk, start=False)
    lst.poll_once(TelegramApi(TOKEN, post))
    assert seen == [("alvo:2", 111)]  # a conversa de fora não muda nada
    calls = [(u.rsplit("/", 1)[1], d) for u, d, _ in post.calls[1:]]
    assert [m for m, _ in calls] == ["answerCallbackQuery", "editMessageText", "answerCallbackQuery"]
    assert calls[1][1]["message_id"] == "77" and "alvo:2" in calls[1][1]["reply_markup"]
