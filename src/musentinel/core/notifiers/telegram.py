"""Telegram via Bot API oficial: texto e print da janela, só ida (comandos não são lidos).

Cada pessoa cria o próprio bot no @BotFather e cola o token no app; quem tocar em
"Iniciar" no bot aparece em "Buscar conversas" e pode ser marcado para receber.
O token vai para o Gerenciador de Credenciais e nunca aparece em log ou mensagem de erro
(a URL da API contém o token, por isso erros mostram só o tipo da exceção).
"""

from __future__ import annotations

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

    def find_chats(self) -> list[tuple[int, str]]:
        """Conversas que mandaram algo ao bot (ex.: tocaram em Iniciar) nas últimas 24 h."""
        updates = self.call("getUpdates", {"timeout": 0, "allowed_updates": '["message","my_chat_member"]'}) or []
        found: dict[int, str] = {}
        for u in updates:
            msg = u.get("message") or u.get("my_chat_member") or {}
            chat = msg.get("chat") or {}
            if "id" not in chat:
                continue
            if chat.get("type") == "private":
                name = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
                if chat.get("username"):
                    name = f"{name} (@{chat['username']})".strip()
            else:
                name = chat.get("title") or "grupo"
            found[int(chat["id"])] = name or str(chat["id"])
        return list(found.items())

    def send_message(self, chat_id: int, text: str) -> None:
        self.call("sendMessage", {"chat_id": str(chat_id), "text": text[:MAX_TEXT],
                                  "disable_web_page_preview": "true"})

    def send_photo(self, chat_id: int, jpeg: bytes, caption: str) -> None:
        self.call("sendPhoto", {"chat_id": str(chat_id), "caption": caption[:MAX_CAPTION]},
                  {"photo": ("print.jpg", jpeg, "image/jpeg")})


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

    def start_inbound(self, on_message) -> None:  # comandos pelo Telegram não fazem parte desta versão
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


def send_test(token: str, chat_id: int, text: str, http_post: HttpPost | None = None) -> tuple[bool, str]:
    """Envio síncrono (botão 'testar'). Retorna (ok, explicação para o usuário)."""
    try:
        TelegramApi(token, http_post).send_message(chat_id, text)
        return True, "mensagem enviada — confira o Telegram"
    except TelegramError as exc:
        return False, exc.description
