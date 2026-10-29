"""WhatsApp via CallMeBot: só texto, só ida, zero infraestrutura.

Cada destinatário tem o próprio telefone e a própria chave (a chave do CallMeBot é
ligada ao número que fez a ativação). Assim cada colega recebe no WhatsApp dele.

GET https://api.callmebot.com/whatsapp.php?phone=<num>&text=<texto>&apikey=<chave>

Fila única com intervalo mínimo entre envios e nova tentativa com espera crescente.
A URL (que contém a chave) nunca vai para log nem para mensagem de erro.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote

from ..config import WhatsAppRecipient, mask_phone
from ..secrets import get_secret
from .base import NotifierStatus

log = logging.getLogger(__name__)

API_URL = "https://api.callmebot.com/whatsapp.php"
SETUP_URL = "https://www.callmebot.com/blog/free-api-whatsapp-messages/"
BACKOFF_S = (5, 15, 45, 120, 300, 600)  # ~18 min tentando (cobre queda curta de internet)
MAX_TEXT = 1500

HttpGet = Callable[[str, float], tuple[int, str]]


def _default_get(url: str, timeout: float) -> tuple[int, str]:
    import httpx

    r = httpx.get(url, timeout=timeout)
    return r.status_code, r.text


def build_url(phone: str, text: str, apikey: str) -> str:
    return f"{API_URL}?phone=%2B{phone}&text={quote(text[:MAX_TEXT], safe='')}&apikey={quote(apikey, safe='')}"


class PermanentError(Exception):
    pass


def classify(status: int, body: str) -> str:
    """'ok', 'retry' ou 'fatal' (chave errada, número não ativado...)."""
    b = (body or "").lower()
    if status == 200 and ("queued" in b or "message sent" in b or "<b>message" in b):
        return "ok"
    if "apikey is invalid" in b or "invalid apikey" in b or ("apikey" in b and "invalid" in b) \
            or "not activated" in b or "phone number" in b and "not" in b and "valid" in b:
        return "fatal"
    if status in (401, 403, 404):
        return "fatal"
    return "retry"


def _summary(body: str) -> str:
    """Trecho legível da resposta do CallMeBot (HTML), sem dados sensíveis."""
    import re

    t = re.sub(r"<[^>]+>", " ", body or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:160]


@dataclass
class _Job:
    recipient: WhatsAppRecipient
    text: str
    attempt: int = 0
    not_before: float = 0.0
    created: float = 0.0


class CallMeBotNotifier:
    name = "WhatsApp (CallMeBot)"
    supports_images = False
    supports_inbound = False
    external = True

    def __init__(self, recipients: list[WhatsAppRecipient], min_interval_s: float = 5.0,
                 http_get: HttpGet | None = None, key_lookup: Callable[[str], str | None] = get_secret,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] | None = None,
                 start: bool = True) -> None:
        self.recipients = [r for r in recipients if r.enabled]
        self.min_interval_s = min_interval_s
        self._get = http_get or _default_get
        self._key = key_lookup
        self._clock = clock
        self._q: queue.Queue[_Job | None] = queue.Queue()
        self._retry: list[_Job] = []
        self._last_send = 0.0
        self._status = NotifierStatus(True, "aguardando")
        self._errors: dict[str, str] = {}
        self._stop = threading.Event()
        self._sleep = sleep or (lambda s: self._stop.wait(s))
        self._thread = threading.Thread(target=self._run, name="callmebot", daemon=True)
        if start:
            self._thread.start()

    # ------------------------------------------------------------------
    def send(self, text: str, image: bytes | None = None) -> None:  # noqa: ARG002 (sem imagem)
        now = self._clock()
        for r in self.recipients:
            self._q.put(_Job(r, text, created=now))

    def start_inbound(self, on_message) -> None:  # CallMeBot não recebe mensagens
        return None

    def status(self) -> NotifierStatus:
        if not self.recipients:
            return NotifierStatus(False, "nenhum número cadastrado")
        if self._errors:
            return NotifierStatus(False, "; ".join(f"{k}: {v}" for k, v in self._errors.items()))
        return self._status

    def pending(self) -> int:
        return self._q.qsize() + len(self._retry)

    def close(self) -> None:
        self._stop.set()
        self._q.put(None)

    # ------------------------------------------------------------------
    def send_now(self, recipient: WhatsAppRecipient, text: str, apikey: str | None = None) -> tuple[bool, str]:
        """Envio síncrono (botão 'testar'). Retorna (ok, explicação para o usuário)."""
        key = apikey or self._key(recipient.secret_key)
        if not key:
            return False, "chave do CallMeBot não cadastrada para este número"
        try:
            status, body = self._get(build_url(recipient.phone, text, key), 20)
        except Exception as exc:
            return False, f"sem conexão com o CallMeBot ({type(exc).__name__})"
        kind = classify(status, body)
        if kind == "ok":
            return True, "mensagem enviada — confira o WhatsApp em alguns segundos"
        if kind == "fatal":
            return False, f"o CallMeBot recusou: {_summary(body) or status}. Confira o número e a chave."
        return False, f"o CallMeBot respondeu {status}: {_summary(body)}"

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
        who = job.recipient.name or mask_phone(job.recipient.phone)
        key = self._key(job.recipient.secret_key)
        self._last_send = self._clock()
        if not key:
            self._errors[who] = "chave não cadastrada"
            log.warning("CallMeBot: %s sem chave cadastrada; mensagem descartada", who)
            return False
        try:
            status, body = self._get(build_url(job.recipient.phone, job.text, key), 20)
            kind = classify(status, body)
            detail = f"HTTP {status}"
        except Exception as exc:
            kind, detail = "retry", f"sem conexão ({type(exc).__name__})"
        if kind == "ok":
            self._errors.pop(who, None)
            late = self._clock() - job.created
            self._status = NotifierStatus(True, "enviado " + time.strftime("%H:%M", time.localtime(self._clock())))
            log.info("CallMeBot: enviado para %s%s", who, f" (atrasado {late:.0f} s)" if late > 30 else "")
            return True
        if kind == "fatal":
            self._errors[who] = "número/chave recusados pelo CallMeBot"
            log.error("CallMeBot: %s recusado (%s); confira número e chave", who, detail)
            return False
        if job.attempt < len(BACKOFF_S):
            job.not_before = self._clock() + BACKOFF_S[job.attempt]
            job.attempt += 1
            self._retry.append(job)
            self._status = NotifierStatus(False, f"tentando de novo ({detail})")
            log.warning("CallMeBot: falhou para %s (%s); tentativa %d em %d s", who, detail,
                        job.attempt, BACKOFF_S[job.attempt - 1])
        else:
            self._status = NotifierStatus(False, f"desisti após {len(BACKOFF_S)} tentativas ({detail})")
            log.error("CallMeBot: desisti de enviar para %s (%s)", who, detail)
        return False
