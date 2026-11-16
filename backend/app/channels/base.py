from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InboundMessage:
    """One customer message, in channel-neutral form."""

    phone_number_id: str  # which of our numbers it was sent to
    sender_phone: str  # E.164, e.g. +919876543210
    sender_name: str | None
    external_id: str
    kind: str  # "text", "audio" or "other"
    text: str
    media_id: str | None
    sent_at: datetime | None


@dataclass(frozen=True)
class StatusUpdate:
    """Delivery progress of a message we sent."""

    phone_number_id: str
    external_id: str
    status: str  # sent, delivered, read, failed
    error: str | None
