from datetime import datetime
from typing import Protocol

from app.db.models import Conversation
from app.schemas.whatsapp import MetaMessage, ParsedInbound


class ChannelAdapter(Protocol):
    channel: str

    def verify_webhook(self, raw: bytes, signature: str) -> bool: ...
    def parse_inbound(self, message: MetaMessage) -> ParsedInbound: ...
    def can_send_freeform(
        self, conversation: Conversation, now: datetime | None = None
    ) -> bool: ...
