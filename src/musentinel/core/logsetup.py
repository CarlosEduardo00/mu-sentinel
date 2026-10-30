"""Logs rotativos (10 MB × 5), sem segredos e com telefones mascarados."""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

from . import paths

_PHONE = re.compile(r"(?<![\w.])\+?\d[\d \-().]{8,18}\d(?![\w.])")
_SECRET = re.compile(r"(?i)(apikey|api_key|token|key|senha|password)=([^&\s]+)")
_TG_TOKEN = re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}")  # token de bot do Telegram


def _mask_phone(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    if len(digits) < 10 or len(digits) > 15:
        return m.group(0)
    return f"+{digits[:2]}{'•' * (len(digits) - 6)}{digits[-4:]}"


def scrub(text: str) -> str:
    """Remove segredos e mascara telefones de um texto."""
    text = _SECRET.sub(lambda m: f"{m.group(1)}=***", text)
    text = _TG_TOKEN.sub("<token-telegram>", text)
    return _PHONE.sub(_mask_phone, text)


class ScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        record.msg = scrub(msg)
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = scrub(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


def logs_dir() -> Path:
    d = paths.data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging(level: int = logging.INFO, to_console: bool = True) -> Path:
    path = logs_dir() / "musentinel.log"
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(ScrubFilter())
    root.addHandler(fh)
    if to_console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh.addFilter(ScrubFilter())
        root.addHandler(sh)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # o httpx loga a URL (com a chave)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return path
