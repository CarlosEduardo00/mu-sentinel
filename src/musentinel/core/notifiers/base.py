"""Interface comum dos notificadores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class NotifierStatus:
    ok: bool
    detail: str


class Notifier(Protocol):
    name: str
    supports_images: bool
    supports_inbound: bool
    external: bool  # sai do PC (WhatsApp/Telegram) — horário silencioso vale para estes

    def send(self, text: str, image: bytes | None = None) -> None: ...

    def start_inbound(self, on_message: Callable[[str, str], None]) -> None: ...  # (remetente, texto)

    def status(self) -> NotifierStatus: ...

    def close(self) -> None: ...
