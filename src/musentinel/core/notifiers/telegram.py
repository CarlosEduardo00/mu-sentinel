"""Telegram via Bot API oficial: alertas (texto e print) e pedidos pelo celular.

Cada pessoa cria o próprio bot no @BotFather e cola o token no app; quem tocar em
"Iniciar" no bot aparece em "Buscar conversas" e pode ser marcado para receber.
Pedidos (/status, /inventario...) só são atendidos para as conversas da lista do app.
O token vai para o Gerenciador de Credenciais e nunca aparece em log ou mensagem de erro
(a URL da API contém o token, por isso erros mostram só o tipo da exceção).
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..config import TELEGRAM_TOKEN_KEY, TelegramChat
from ..secrets import get_secret
from .base import NotifierStatus

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
BOTFATHER_URL = "https://t.me/BotFather"
BACKOFF_S = (5, 15, 45, 120, 300, 600)
MAX_TEXT = 4000
MAX_CAPTION = 1000

# (método, campos, arquivos) -> (status HTTP, JSON da resposta)
HttpPost = Callable[[str, dict, dict | None], tuple[int, dict]]


class TelegramError(Exception):
    def __init__(self, kind: str, description: str, retry_after: float | None = None):
        super().__init__(description)
        self.kind = kind  # "token" | "chat" | "retry"
        self.description = description
        self.retry_after = retry_after


def _default_post(url: str, data: dict, files: dict | None) -> tuple[int, dict]:
    import httpx

    r = httpx.post(url, data=data, files=files, timeout=30)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"ok": False, "description": f"resposta inválida (HTTP {r.status_code})"}


class TelegramApi:
    def __init__(self, token: str, http_post: HttpPost | None = None) -> None:
        self._token = token
        self._post = http_post or _default_post

    def call(self, method: str, data: dict | None = None, files: dict | None = None) -> Any:
        url = f"{API}/bot{self._token}/{method}"
        try:
            status, body = self._post(url, data or {}, files)
        except Exception as exc:  # sem rede, DNS, timeout... (str(exc) pode conter a URL com o token)
            raise TelegramError("retry", f"sem conexão com o Telegram ({type(exc).__name__})") from None
        if body.get("ok"):
            return body.get("result")
        desc = str(body.get("description") or f"HTTP {status}")
        code = int(body.get("error_code") or status)
        if code == 401 or code == 404:
            raise TelegramError("token", "token do bot inválido (confira o que o @BotFather mandou)")
        if code == 409:
            raise TelegramError("retry", "outro programa (ou outra cópia do MU Sentinel) está lendo as mensagens "
                                         "deste bot", 10)
        if code == 429:
            ra = float((body.get("parameters") or {}).get("retry_after") or 5)
            raise TelegramError("retry", "muitas mensagens seguidas; aguardando o Telegram", ra)
        if code in (400, 403):
            low = desc.lower()
            if "chat not found" in low:
                raise TelegramError("chat", "conversa não encontrada: a pessoa precisa tocar em Iniciar no bot")
            if "blocked" in low or "deactivated" in low or "kicked" in low:
                raise TelegramError("chat", "a pessoa bloqueou ou saiu do bot")
            raise TelegramError("chat", f"o Telegram recusou: {desc[:120]}")
        raise TelegramError("retry", f"o Telegram respondeu {code}: {desc[:120]}")

    # ------------------------------------------------------------------
    def get_me(self) -> dict:
        return self.call("getMe")

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict]:
        data = {"timeout": timeout, "allowed_updates": '["message","my_chat_member","callback_query"]'}
        if offset is not None:
            data["offset"] = offset
        return self.call("getUpdates", data) or []

    def find_chats(self) -> list[tuple[int, str]]:
        """Conversas que mandaram algo ao bot (ex.: tocaram em Iniciar) nas últimas 24 h."""
        if listener_running():  # a escuta de comandos já consome as mensagens: usa o que ela viu
            return seen_chats()
        found = remember_chats(self.get_updates())
        return list(found.items())

    def send_message(self, chat_id: int, text: str, keyboard: list[list[str]] | None = None,
                     buttons: list[list[tuple[str, str]]] | None = None) -> None:
        data = {"chat_id": str(chat_id), "text": text[:MAX_TEXT], "disable_web_page_preview": "true"}
        if buttons:
            data["reply_markup"] = _buttons_json(buttons)
        elif keyboard:
            data["reply_markup"] = _keyboard_json(keyboard)
        self.call("sendMessage", data)

    def edit_message(self, chat_id: int, message_id: int, text: str,
                     buttons: list[list[tuple[str, str]]] | None = None) -> None:
        data = {"chat_id": str(chat_id), "message_id": str(message_id), "text": text[:MAX_TEXT]}
        if buttons:
            data["reply_markup"] = _buttons_json(buttons)
        self.call("editMessageText", data)

    def answer_button(self, callback_id: str, text: str = "") -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})

    def send_photo(self, chat_id: int, jpeg: bytes, caption: str, keyboard: list[list[str]] | None = None) -> None:
        data = {"chat_id": str(chat_id), "caption": caption[:MAX_CAPTION]}
        if keyboard:
            data["reply_markup"] = _keyboard_json(keyboard)
        self.call("sendPhoto", data, {"photo": ("print.jpg", jpeg, "image/jpeg")})

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        self.call("setMyCommands", {"commands": json.dumps(
            [{"command": c, "description": d} for c, d in commands], ensure_ascii=False)})


def _keyboard_json(rows: list[list[str]]) -> str:
    return json.dumps({"keyboard": [[{"text": t} for t in row] for row in rows],
                       "resize_keyboard": True, "is_persistent": True}, ensure_ascii=False)


def _buttons_json(rows: list[list[tuple[str, str]]]) -> str:
    return json.dumps({"inline_keyboard": [[{"text": t, "callback_data": d[:64]} for t, d in row] for row in rows]},
                      ensure_ascii=False)


# conversas vistas pelo bot nesta execução (para "Buscar conversas" enquanto a escuta está ligada)
_seen_lock = threading.Lock()
_SEEN: dict[int, str] = {}
_LISTENERS = 0


def chat_name(chat: dict) -> str:
    if chat.get("type") == "private":
        name = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
        if chat.get("username"):
            name = f"{name} (@{chat['username']})".strip()
    else:
        name = chat.get("title") or "grupo"
    return name or str(chat.get("id"))


def remember_chats(updates: list[dict]) -> dict[int, str]:
    found: dict[int, str] = {}
    for u in updates:
        msg = u.get("message") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            found[int(chat["id"])] = chat_name(chat)
    with _seen_lock:
        _SEEN.update(found)
    return found


def seen_chats() -> list[tuple[int, str]]:
    with _seen_lock:
        return list(_SEEN.items())


def listener_running() -> bool:
    return _LISTENERS > 0


@dataclass
class _Job:
    chat: TelegramChat
    text: str
    image: bytes | None = None
    attempt: int = 0
    not_before: float = 0.0
    created: float = 0.0


class TelegramNotifier:
    name = "Telegram"
    supports_images = True
    supports_inbound = False
    external = True

    def __init__(self, chats: list[TelegramChat], min_interval_s: float = 1.0, send_images: bool = True,
                 http_post: HttpPost | None = None, token_lookup: Callable[[str], str | None] = get_secret,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] | None = None,
                 start: bool = True) -> None:
        self.chats = [c for c in chats if c.enabled]
        self.min_interval_s = min_interval_s
        self.send_images = send_images
        self._post = http_post
        self._token = token_lookup
        self._clock = clock
        self._q: queue.Queue[_Job | None] = queue.Queue()
        self._retry: list[_Job] = []
        self._last_send = 0.0
        self._status = NotifierStatus(True, "aguardando")
        self._errors: dict[str, str] = {}
        self._token_error: str | None = None
        self._stop = threading.Event()
        self._sleep = sleep or (lambda s: self._stop.wait(s))
        self._thread = threading.Thread(target=self._run, name="telegram", daemon=True)
        if start:
            self._thread.start()

    def _api(self) -> TelegramApi | None:
        token = self._token(TELEGRAM_TOKEN_KEY)
        return TelegramApi(token, self._post) if token else None

    # ------------------------------------------------------------------
    def send(self, text: str, image: bytes | None = None) -> None:
        now = self._clock()
        for c in self.chats:
            self._q.put(_Job(c, text, image if self.send_images else None, created=now))

    def start_inbound(self, on_message) -> None:  # os pedidos são lidos pelo TelegramCommandListener
        return None

    def status(self) -> NotifierStatus:
        if not self.chats:
            return NotifierStatus(False, "nenhuma conversa marcada")
        if self._token_error:
            return NotifierStatus(False, self._token_error)
        if self._errors:
            return NotifierStatus(False, "; ".join(f"{k}: {v}" for k, v in self._errors.items()))
        return self._status

    def pending(self) -> int:
        return self._q.qsize() + len(self._retry)

    def close(self) -> None:
        self._stop.set()
        self._q.put(None)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._next_job()
            if job is None:
                continue
            wait = max(0.0, self._last_send + self.min_interval_s - self._clock())
            if wait:
                self._sleep(wait)
            self._deliver(job)

    def _next_job(self) -> _Job | None:
        now = self._clock()
        due = [j for j in self._retry if j.not_before <= now]
        if due:
            j = min(due, key=lambda j: j.not_before)
            self._retry.remove(j)
            return j
        timeout = 1.0
        if self._retry:
            timeout = max(0.05, min(1.0, min(j.not_before for j in self._retry) - now))
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def _deliver(self, job: _Job) -> bool:
        who = job.chat.name or str(job.chat.chat_id)
        self._last_send = self._clock()
        api = self._api()
        if api is None:
            self._token_error = "token do bot não cadastrado"
            log.warning("Telegram: token não cadastrado; mensagem descartada")
            return False
        try:
            if job.image:
                api.send_photo(job.chat.chat_id, job.image, job.text)
            else:
                api.send_message(job.chat.chat_id, job.text)
        except TelegramError as exc:
            if exc.kind == "token":
                self._token_error = exc.description
                log.error("Telegram: %s", exc.description)
                return False
            if exc.kind == "chat":
                self._errors[who] = exc.description
                log.error("Telegram: %s (%s)", exc.description, who)
                return False
            if job.attempt < len(BACKOFF_S):
                delay = exc.retry_after or BACKOFF_S[job.attempt]
                job.not_before = self._clock() + delay
                job.attempt += 1
                self._retry.append(job)
                self._status = NotifierStatus(False, f"tentando de novo ({exc.description})")
                log.warning("Telegram: falhou para %s (%s); tentativa %d em %.0f s", who, exc.description,
                            job.attempt, delay)
            else:
                self._status = NotifierStatus(False, f"desisti após {len(BACKOFF_S)} tentativas")
                log.error("Telegram: desisti de enviar para %s (%s)", who, exc.description)
            return False
        self._token_error = None
        self._errors.pop(who, None)
        late = self._clock() - job.created
        self._status = NotifierStatus(True, "enviado " + time.strftime("%H:%M", time.localtime(self._clock())))
        log.info("Telegram: enviado para %s%s", who, f" (atrasado {late:.0f} s)" if late > 30 else "")
        return True


NOT_ALLOWED_TEXT = ("Oi! Este bot avisa sobre o MU de outra pessoa. Se você deve receber os alertas, peça para "
                    "o dono clicar em \"Buscar conversas\" no MU Sentinel.")

# (texto do pedido, conversa) -> respostas [(texto, jpeg ou None, botões ou None)]
Handler = Callable[[str, int], list[tuple]]
# (dado do botão, conversa) -> (aviso curto, (texto novo, botões novos) ou None)
ButtonHandler = Callable[[str, int], tuple[str, tuple | None]]


class TelegramCommandListener:
    """Lê as mensagens mandadas ao bot (long polling) e responde aos pedidos de quem está na lista.

    - Só atende conversas cujo ID está em `allowed` (as cadastradas no app).
    - Mensagens antigas (enviadas com o app fechado) são ignoradas: o pedido já perdeu o sentido.
    - O token só é lido do Gerenciador de Credenciais; erros nunca mostram a URL.
    """

    POLL_S = 20
    MAX_AGE_S = 120

    def __init__(self, allowed: set[int], handler: Handler, keyboard: list[list[str]] | None = None,
                 commands: list[tuple[str, str]] | None = None, http_post: HttpPost | None = None,
                 token_lookup: Callable[[str], str | None] = get_secret, clock: Callable[[], float] = time.time,
                 start: bool = True, on_button: ButtonHandler | None = None) -> None:
        self.allowed = set(allowed)
        self.handler = handler
        self.on_button = on_button
        self.keyboard = keyboard
        self.commands = commands
        self._post = http_post
        self._token = token_lookup
        self._clock = clock
        self._offset: int | None = None
        self._greeted: set[int] = set()
        self._stop = threading.Event()
        self.status = NotifierStatus(True, "aguardando pedidos")
        self._thread = threading.Thread(target=self._run, name="telegram-comandos", daemon=True)
        self._counted = False
        if start:
            self._mark(True)
            self._thread.start()

    def _mark(self, on: bool) -> None:
        global _LISTENERS
        with _seen_lock:
            if on and not self._counted:
                _LISTENERS += 1
                self._counted = True
            elif not on and self._counted:
                _LISTENERS -= 1
                self._counted = False

    def close(self) -> None:
        self._stop.set()
        self._mark(False)

    # ------------------------------------------------------------------
    def _api(self) -> TelegramApi | None:
        token = self._token(TELEGRAM_TOKEN_KEY)
        return TelegramApi(token, self._post) if token else None

    def _run(self) -> None:
        delay_i = 0
        announced = False
        while not self._stop.is_set():
            api = self._api()
            if api is None:
                self.status = NotifierStatus(False, "token do bot não cadastrado")
                self._stop.wait(30)
                continue
            if not announced and self.commands:
                try:
                    api.set_commands(self.commands)  # menu "/" do bot
                except TelegramError:
                    pass
                announced = True
            try:
                self.poll_once(api, timeout=self.POLL_S)
                delay_i = 0
            except TelegramError as exc:
                self.status = NotifierStatus(False, exc.description)
                wait = 60 if exc.kind == "token" else (exc.retry_after or BACKOFF_S[min(delay_i, len(BACKOFF_S) - 1)])
                delay_i += 1
                log.warning("Telegram (pedidos): %s; tentando de novo em %.0f s", exc.description, wait)
                self._stop.wait(wait)

    def poll_once(self, api: TelegramApi, timeout: int = 0) -> int:
        """Busca as mensagens novas e responde. Retorna quantos pedidos atendeu."""
        updates = api.get_updates(self._offset, timeout)
        if self._stop.is_set():
            return 0
        self.status = NotifierStatus(True, "aguardando pedidos")
        remember_chats(updates)
        served = 0
        for u in updates:
            self._offset = int(u["update_id"]) + 1
            if u.get("callback_query"):
                self._button(api, u["callback_query"])
                continue
            msg = u.get("message") or {}
            chat_id = (msg.get("chat") or {}).get("id")
            text = (msg.get("text") or "").strip()
            if chat_id is None or not text:
                continue
            chat_id = int(chat_id)
            if chat_id not in self.allowed:
                if text.startswith("/start") and chat_id not in self._greeted:
                    self._greeted.add(chat_id)
                    self._reply(api, chat_id, [(NOT_ALLOWED_TEXT, None)], keyboard=False)
                log.info("Telegram: pedido ignorado de uma conversa fora da lista")
                continue
            if self._clock() - float(msg.get("date") or 0) > self.MAX_AGE_S:
                continue  # mandado com o app fechado
            log.info("Telegram: pedido recebido: %s", text[:40])
            try:
                replies = self.handler(text, chat_id)
            except Exception:
                log.exception("Telegram: erro ao atender pedido")
                replies = [("Não consegui atender o pedido (erro interno; detalhes no log do app).", None)]
            self._reply(api, chat_id, replies)
            served += 1
        return served

    def _button(self, api: TelegramApi, cq: dict) -> None:
        """Toque num botão de uma mensagem do bot (ex.: escolher o personagem)."""
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        toast, new = "", None
        if chat_id is not None and int(chat_id) in self.allowed and self.on_button:
            try:
                toast, new = self.on_button(str(cq.get("data") or ""), int(chat_id))
            except Exception:
                log.exception("Telegram: erro no botão")
        try:
            api.answer_button(str(cq.get("id")), toast)
            if new and msg.get("message_id") is not None:
                api.edit_message(int(chat_id), int(msg["message_id"]), new[0], new[1])
        except TelegramError as exc:
            log.warning("Telegram: botão sem resposta (%s)", exc.description)

    def _reply(self, api: TelegramApi, chat_id: int, replies, keyboard: bool = True) -> None:
        for i, item in enumerate(replies):
            text, image = item[0], item[1]
            buttons = item[2] if len(item) > 2 else None
            kb = self.keyboard if keyboard and i == len(replies) - 1 else None
            for attempt in range(2):
                try:
                    if image:
                        api.send_photo(chat_id, image, text, kb)
                        if len(text) > MAX_CAPTION:  # legenda longa: manda o resto como texto
                            api.send_message(chat_id, text[MAX_CAPTION:], kb)
                    else:
                        api.send_message(chat_id, text, kb, buttons)
                    break
                except TelegramError as exc:
                    if exc.kind == "retry" and exc.retry_after and attempt == 0:
                        self._stop.wait(min(exc.retry_after, 30))
                        continue
                    log.warning("Telegram: resposta não enviada (%s)", exc.description)
                    break


def send_test(token: str, chat_id: int, text: str, http_post: HttpPost | None = None) -> tuple[bool, str]:
    """Envio síncrono (botão 'testar'). Retorna (ok, explicação para o usuário)."""
    try:
        TelegramApi(token, http_post).send_message(chat_id, text)
        return True, "mensagem enviada — confira o Telegram"
    except TelegramError as exc:
        return False, exc.description
