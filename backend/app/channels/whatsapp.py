import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import DomainError
from app.db.models import Conversation
from app.db.models.conversation import ConversationStatus
from app.schemas.whatsapp import MetaMessage, ParsedInbound


class GraphRejected(DomainError):
    def __init__(self, status: int, code: str = "provider_rejected") -> None:
        super().__init__("WhatsApp request rejected; check channel delivery details", 502)
        self.provider_status, self.code = status, code


class GraphAmbiguous(DomainError):
    def __init__(self) -> None:
        super().__init__("WhatsApp acceptance is uncertain; reconcile before resending", 502)


class WhatsAppGraph:
    # Meta official examples: https://www.postman.com/meta/whatsapp-business-platform/folder/o48mro7/messages
    def __init__(
        self, config: Settings, token: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if not re.fullmatch(r"v[0-9]+\.0", config.whatsapp_api_version):
            raise DomainError("Configure a supported WHATSAPP_API_VERSION", 503)
        self.config, self.token, self.transport = config, token, transport

    async def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        pdf: bytes | None = None,
    ) -> dict[str, Any]:
        if not re.fullmatch(
            r"[0-9]+(?:/(?:messages|media|message_templates|phone_numbers))?", path
        ):
            raise DomainError("Invalid WhatsApp resource")
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.config.whatsapp_timeout_s,
            headers={"Authorization": "Bearer " + self.token},
            follow_redirects=False,
        ) as client:
            response = await client.request(
                method,
                "https://graph.facebook.com/" + self.config.whatsapp_api_version + "/" + path,
                json=payload,
                params=params,
                files={"file": ("quotation.pdf", pdf, "application/pdf")}
                if pdf is not None
                else None,
                data={"messaging_product": "whatsapp", "type": "application/pdf"}
                if pdf is not None
                else None,
            )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not response.is_success:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            code = error.get("code") if isinstance(error, dict) else None
            raise GraphRejected(
                response.status_code, str(code) if isinstance(code, int) else "provider_rejected"
            )
        if not isinstance(body, dict):
            raise GraphAmbiguous()
        return body

    async def list_resources(self, path: str, fields: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        params = {"fields": fields, "limit": "100"}
        for _ in range(20):
            body = await self.request("GET", path, params=params)
            values = body.get("data")
            if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
                raise DomainError("Invalid WhatsApp registry response", 502)
            rows.extend(values)
            paging = body.get("paging", {})
            if not isinstance(paging, dict) or not paging.get("next"):
                return rows
            after = paging.get("cursors", {}).get("after")
            if not isinstance(after, str) or not after:
                raise DomainError("Invalid WhatsApp pagination", 502)
            # Use a fixed host/path and cursor; never follow a token-bearing arbitrary next URL.
            params["after"] = after
        raise DomainError("WhatsApp registry is too large; narrow the connected account", 502)

    async def verify_account(self, phone_id: str, waba_id: str) -> None:
        phones = await self.list_resources(waba_id + "/phone_numbers", "id")
        if not any(str(phone.get("id")) == phone_id for phone in phones):
            raise DomainError("Phone number does not belong to this WhatsApp business account", 409)

    async def upload_pdf(self, phone_id: str, pdf: bytes) -> str:
        response = await self.request("POST", phone_id + "/media", pdf=pdf)
        media_id = response.get("id")
        if not isinstance(media_id, str) or not media_id.isdecimal():
            raise DomainError("Invalid WhatsApp media upload response", 502)
        return media_id

    async def send(self, phone_id: str, payload: dict[str, Any]) -> str:
        response = await self.request("POST", phone_id + "/messages", payload=payload)
        messages = response.get("messages")
        if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict):
            raise GraphAmbiguous()
        provider_id = messages[0].get("id")
        if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 512:
            raise GraphAmbiguous()
        return provider_id


class WhatsAppAdapter:
    channel = "whatsapp"

    def __init__(self, config: Settings) -> None:
        self.config = config

    def verify_webhook(self, raw: bytes, signature: str) -> bool:
        secret = self.config.whatsapp_app_secret.get_secret_value()
        if not secret or not signature.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def can_send_freeform(self, conversation: Conversation, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        last = conversation.last_customer_msg_at
        # Current policy: https://business.whatsapp.com/policy
        return bool(
            conversation.status == ConversationStatus.OPEN
            and last
            and timedelta(0) <= now - last < timedelta(hours=24)
        )

    def parse_inbound(self, message: MetaMessage) -> ParsedInbound:
        try:
            timestamp = datetime.fromtimestamp(int(message.timestamp), UTC)
        except (ValueError, OverflowError, OSError) as error:
            raise DomainError("Invalid WhatsApp message timestamp") from error
        if timestamp > datetime.now(UTC) + timedelta(minutes=5):
            raise DomainError("WhatsApp message timestamp is in the future")
        text, kind, attachments = (
            "Customer sent unsupported content. Please review with the team.",
            "unsupported",
            [],
        )
        if message.type == "text" and message.text:
            text, kind = message.text.body, "text"
        elif message.type == "interactive" and message.interactive:
            reply = message.interactive.button_reply or message.interactive.list_reply
            if reply:
                text, kind = reply.title, "text"
        elif message.type == "button" and message.button:
            text, kind = message.button.text, "text"
        elif message.type in {"image", "document"}:
            media = message.image if message.type == "image" else message.document
            if media:
                text, kind = "Customer sent " + message.type + ". Team review required.", "media"
                filename = re.sub(
                    r"[^A-Za-z0-9 ._-]", "", media.filename.replace("\\", "/").split("/")[-1]
                )[:100]
                attachments = [
                    {
                        "media_id": media.id,
                        "mime_type": media.mime_type,
                        "filename": filename,
                        "kind": message.type,
                    }
                ]
                if media.caption:
                    text += " Caption: " + media.caption[:3500]
        return ParsedInbound(
            provider_id=message.id,
            wa_id=message.from_,
            timestamp=timestamp,
            content=text,
            content_type=kind,
            attachments=attachments,
        )
