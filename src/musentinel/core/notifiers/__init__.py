"""Notificadores: WhatsApp (CallMeBot) e, pela GUI, notificação do Windows."""

from __future__ import annotations

from .base import Notifier, NotifierStatus
from .callmebot import CallMeBotNotifier
from .telegram import TelegramNotifier


class FakeNotifier:
    """Para testes: guarda o que foi enviado."""

    name = "fake"
    supports_images = False
    supports_inbound = False

    def __init__(self, external: bool = True) -> None:
        self.external = external
        self.sent: list[str] = []
        self.images: list[bytes | None] = []

    def send(self, text: str, image: bytes | None = None) -> None:
        self.sent.append(text)
        self.images.append(image)

    def start_inbound(self, on_message) -> None:
        return None

    def status(self) -> NotifierStatus:
        return NotifierStatus(True, "ok")

    def close(self) -> None:
        pass


__all__ = ["CallMeBotNotifier", "FakeNotifier", "Notifier", "NotifierStatus", "TelegramNotifier"]
