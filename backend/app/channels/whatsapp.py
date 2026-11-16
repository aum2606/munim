"""WhatsApp Cloud API: webhook verification and parsing, and sending.

Checked against Meta's docs on 2026-11-16:
- Webhook setup:  https://developers.facebook.com/docs/graph-api/webhooks/getting-started
  (GET verify echoes hub.challenge; POST carries X-Hub-Signature-256: sha256=<HMAC-SHA256 of the
  raw body, keyed with the app secret>)
- Messages API:   https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
- Media:          https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media
"""

import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from app.channels.base import InboundMessage, StatusUpdate

log = structlog.get_logger()

GRAPH_URL = "https://graph.facebook.com"
MAX_TEXT_CHARS = 4096  # WhatsApp's limit for a text message body
_PHONE = re.compile(r"^\d{8,15}$")
SERVICE_WINDOW = timedelta(hours=24)


def window_open(last_customer_msg_at: datetime | None, now: datetime) -> bool:
    """Free-form messages are only allowed within 24 hours of the customer's last message; after
    that only approved templates, which we do not send (DECISIONS)."""
    return last_customer_msg_at is not None and now - last_customer_msg_at < SERVICE_WINDOW


class WhatsAppError(Exception):
    """A call to Meta failed. `permanent` is true when retrying cannot help (bad token, bad
    number); false for rate limits and server errors."""

    def __init__(self, status: int, permanent: bool, detail: str = "") -> None:
        super().__init__(f"WhatsApp API error {status}")
        self.status = status
        self.permanent = permanent
        self.detail = detail


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """Constant-time check that the body was signed by Meta. Fails closed without a secret."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def verify_challenge(
    verify_token: str, mode: str | None, token: str | None, challenge: str | None
) -> str | None:
    """The challenge to echo back, or None to refuse the subscription."""
    if not verify_token or mode != "subscribe" or challenge is None or token is None:
        return None
    return challenge if hmac.compare_digest(token.encode(), verify_token.encode()) else None


def parse_webhook(payload: object) -> tuple[list[InboundMessage], list[StatusUpdate]]:
    """Pull messages and delivery statuses out of a webhook body. Anything unexpected is skipped:
    the body is only parsed after the signature check, but its shape is still not trusted."""
    messages: list[InboundMessage] = []
    statuses: list[StatusUpdate] = []
    for entry in _list(_dict(payload).get("entry")):
        for change in _list(_dict(entry).get("changes")):
            value = _dict(_dict(change).get("value"))
            number_id = str(_dict(value.get("metadata")).get("phone_number_id") or "")
            if not number_id:
                continue
            names = {
                str(c.get("wa_id")): _dict(c.get("profile")).get("name")
                for c in map(_dict, _list(value.get("contacts")))
                if c.get("wa_id")
            }
            for raw in map(_dict, _list(value.get("messages"))):
                message = _message(number_id, raw, names)
                if message:
                    messages.append(message)
            for raw in map(_dict, _list(value.get("statuses"))):
                if raw.get("id") and raw.get("status"):
                    errors = _list(raw.get("errors"))
                    error = _dict(errors[0]).get("title") if errors else None
                    statuses.append(
                        StatusUpdate(
                            number_id,
                            str(raw["id"]),
                            str(raw["status"]),
                            str(error)[:200] if error else None,
                        )
                    )
    return messages, statuses


def _message(number_id: str, raw: dict[str, Any], names: dict[str, Any]) -> InboundMessage | None:
    sender = str(raw.get("from") or "")
    # A user who adopted a WhatsApp username may arrive without a phone number. We cannot reply
    # to them yet (DECISIONS), so they are skipped rather than stored half-identified.
    if not raw.get("id") or not _PHONE.match(sender):
        return None
    kind, text, media_id = "other", "", None
    if raw.get("type") == "text":
        kind, text = "text", str(_dict(raw.get("text")).get("body") or "")
    elif raw.get("type") == "audio":
        kind, media_id = "audio", str(_dict(raw.get("audio")).get("id") or "") or None
    name = names.get(sender)
    return InboundMessage(
        phone_number_id=number_id,
        sender_phone=f"+{sender}",
        sender_name=str(name)[:120] if name else None,
        external_id=str(raw["id"]),
        kind=kind,
        text=text,
        media_id=media_id,
        sent_at=_timestamp(raw.get("timestamp")),
    )


def _timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)), UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


class WhatsAppClient:
    """Sends messages and fetches media for one business's number."""

    def __init__(
        self, http: httpx.AsyncClient, version: str, phone_number_id: str, token: str
    ) -> None:
        self._http = http
        self._base = f"{GRAPH_URL}/{version}"
        self._number_id = phone_number_id
        self._headers = {"Authorization": f"Bearer {token}"}

    async def send_text(self, to_phone: str, body: str) -> str:
        return await self._send(to_phone, {"type": "text", "text": {"body": body[:MAX_TEXT_CHARS]}})

    async def send_document(self, to_phone: str, pdf: bytes, filename: str, caption: str) -> str:
        media_id = await self._upload(pdf, filename, "application/pdf")
        document = {"id": media_id, "filename": filename, "caption": caption[:1024]}
        return await self._send(to_phone, {"type": "document", "document": document})

    async def download_media(self, media_id: str, max_bytes: int) -> tuple[bytes, str]:
        """The media URL Meta returns expires in minutes and needs the same bearer token."""
        info = await self._request("GET", f"{self._base}/{media_id}")
        url = str(info.get("url") or "")
        if not url.startswith("https://") or int(info.get("file_size") or 0) > max_bytes:
            raise WhatsAppError(400, True, "media url or size not acceptable")
        response = await self._http.get(url, headers=self._headers, timeout=30)
        _raise_for_status(response)
        if len(response.content) > max_bytes:
            raise WhatsAppError(413, True, "media too large")
        return response.content, str(info.get("mime_type") or "audio/ogg")

    async def _send(self, to_phone: str, content: dict[str, Any]) -> str:
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.removeprefix("+"),
            **content,
        }
        data = await self._request("POST", f"{self._base}/{self._number_id}/messages", json=body)
        sent = _list(data.get("messages"))
        if not sent or not _dict(sent[0]).get("id"):
            raise WhatsAppError(502, False, "no message id in response")
        return str(_dict(sent[0])["id"])

    async def _upload(self, content: bytes, filename: str, mime_type: str) -> str:
        data = await self._request(
            "POST",
            f"{self._base}/{self._number_id}/media",
            data={"messaging_product": "whatsapp"},
            files={"file": (filename, content, mime_type)},
        )
        if not data.get("id"):
            raise WhatsAppError(502, False, "no media id in response")
        return str(data["id"])

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._http.request(
                method, url, headers=self._headers, timeout=30, **kwargs
            )
        except httpx.HTTPError as exc:  # network trouble is worth retrying
            raise WhatsAppError(0, False, type(exc).__name__) from exc
        _raise_for_status(response)
        return _dict(response.json())


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    # Only Meta's error code and type: the message text can echo what we sent.
    error = _dict(_dict(response.json() if response.content else {}).get("error"))
    detail = f"{error.get('type', '')} {error.get('code', '')}".strip()
    retryable = response.status_code == 429 or response.status_code >= 500
    log.warning("whatsapp_api_error", status=response.status_code, detail=detail)
    raise WhatsAppError(response.status_code, not retryable, detail)
