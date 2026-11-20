"""The WhatsApp adapter without a database: signatures, parsing, the 24-hour window, the HTTP
client against a fake Meta, and credential encryption."""

import hashlib
import hmac
import json
import math
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from app.channels.whatsapp import (
    WhatsAppClient,
    WhatsAppError,
    parse_webhook,
    verify_challenge,
    verify_signature,
    window_open,
)
from app.core.config import Settings
from app.core.crypto import decrypt_credentials, encrypt_credentials
from app.llm.transcriber import WhisperTranscriber

SECRET = "app-secret-for-tests"


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --- signature and subscription check ----------------------------------------------------------


def test_signature_accepts_only_the_exact_body_signed_with_the_secret() -> None:
    body = b'{"entry": []}'
    assert verify_signature(SECRET, body, sign(body))
    assert not verify_signature(SECRET, body + b" ", sign(body))  # body altered
    assert not verify_signature(SECRET, body, sign(body, "another-secret"))
    assert not verify_signature(SECRET, body, sign(body).removeprefix("sha256="))  # no prefix
    assert not verify_signature(SECRET, body, None)
    assert not verify_signature(SECRET, body, "sha256=")


def test_signature_fails_closed_when_no_secret_is_configured() -> None:
    body = b"{}"
    assert not verify_signature("", body, sign(body, ""))


def test_subscription_challenge_is_echoed_only_for_the_right_token() -> None:
    assert verify_challenge("tok", "subscribe", "tok", "12345") == "12345"
    assert verify_challenge("tok", "subscribe", "wrong", "12345") is None
    assert verify_challenge("tok", "unsubscribe", "tok", "12345") is None
    assert verify_challenge("tok", "subscribe", None, "12345") is None
    assert verify_challenge("tok", "subscribe", "tok", None) is None
    assert verify_challenge("", "subscribe", "", "12345") is None  # unconfigured: refuse


# --- parsing --------------------------------------------------------------------------------


def webhook(*, messages: list[dict[str, object]] | None = None, statuses: object = None) -> dict:
    value: dict[str, object] = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550001111", "phone_number_id": "PNID1"},
        "contacts": [{"profile": {"name": "Asha"}, "wa_id": "919876543210"}],
    }
    if messages is not None:
        value["messages"] = messages
    if statuses is not None:
        value["statuses"] = statuses
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": value}]}]}


def test_parses_text_and_voice_messages() -> None:
    messages, statuses = parse_webhook(
        webhook(
            messages=[
                {
                    "from": "919876543210",
                    "id": "wamid.T1",
                    "timestamp": "1700000000",
                    "type": "text",
                    "text": {"body": "500 visiting card ka rate?"},
                },
                {
                    "from": "919876543210",
                    "id": "wamid.A1",
                    "timestamp": "1700000001",
                    "type": "audio",
                    "audio": {"id": "MEDIA9", "mime_type": "audio/ogg; codecs=opus", "voice": True},
                },
                {"from": "919876543210", "id": "wamid.I1", "type": "image", "image": {"id": "x"}},
            ]
        )
    )
    assert statuses == []
    text, voice, other = messages
    assert (text.kind, text.text, text.external_id) == (
        "text",
        "500 visiting card ka rate?",
        "wamid.T1",
    )
    assert (text.sender_phone, text.sender_name, text.phone_number_id) == (
        "+919876543210",
        "Asha",
        "PNID1",
    )
    assert text.sent_at == datetime.fromtimestamp(1700000000, UTC)
    assert (voice.kind, voice.media_id) == ("audio", "MEDIA9")
    assert (other.kind, other.text, other.media_id) == ("other", "", None)


def test_parses_delivery_statuses_with_their_error() -> None:
    _, statuses = parse_webhook(
        webhook(
            statuses=[
                {"id": "wamid.O1", "status": "delivered"},
                {"id": "wamid.O2", "status": "failed", "errors": [{"title": "Re-engagement"}]},
            ]
        )
    )
    assert [(s.external_id, s.status, s.error) for s in statuses] == [
        ("wamid.O1", "delivered", None),
        ("wamid.O2", "failed", "Re-engagement"),
    ]


def test_skips_anything_that_is_not_a_phone_message() -> None:
    # No phone number (a username-only user), an id-less message, and junk where lists belong.
    messages, statuses = parse_webhook(
        webhook(
            messages=[
                {
                    "from_user_id": "BSUID.1",
                    "id": "wamid.U1",
                    "type": "text",
                    "text": {"body": "hi"},
                },
                {"from": "919876543210", "type": "text", "text": {"body": "no id"}},
                {"from": "not-a-phone", "id": "wamid.X", "type": "text", "text": {"body": "hi"}},
            ],
            statuses=[{"status": "sent"}, "junk"],
        )
    )
    assert messages == [] and statuses == []


@pytest.mark.parametrize(
    "payload",
    [None, [], "x", {}, {"entry": "x"}, {"entry": [None, {"changes": [None, {"value": 3}]}]}],
)
def test_parsing_never_raises_on_unexpected_shapes(payload: object) -> None:
    assert parse_webhook(payload) == ([], [])


def test_a_payload_without_our_phone_number_id_is_ignored() -> None:
    payload = webhook(messages=[{"from": "919876543210", "id": "w", "type": "text", "text": {}}])
    payload["entry"][0]["changes"][0]["value"]["metadata"] = {}
    assert parse_webhook(payload) == ([], [])


def test_audio_without_a_media_id_is_not_treated_as_a_voice_note() -> None:
    (message,), _ = parse_webhook(
        webhook(messages=[{"from": "919876543210", "id": "w", "type": "audio", "audio": {}}])
    )
    assert message.kind == "audio" and message.media_id is None


# --- the 24-hour window ----------------------------------------------------------------------


def test_window_is_open_for_24_hours_after_the_customers_last_message() -> None:
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    assert window_open(now - timedelta(hours=23, minutes=59), now)
    assert not window_open(now - timedelta(hours=24), now)
    assert not window_open(None, now)


# --- the HTTP client against a fake Meta ----------------------------------------------------------


def client_with(handler: httpx.MockTransport) -> WhatsAppClient:
    return WhatsAppClient(httpx.AsyncClient(transport=handler), "v24.0", "PNID1", "token-123")


async def test_send_text_posts_the_documented_body_with_the_bearer_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.OUT"}]})

    wa_id = await client_with(httpx.MockTransport(handler)).send_text("+919876543210", "Hello")
    assert wa_id == "wamid.OUT"
    (request,) = seen
    assert str(request.url) == "https://graph.facebook.com/v24.0/PNID1/messages"
    assert request.headers["Authorization"] == "Bearer token-123"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "919876543210",  # no leading +
        "type": "text",
        "text": {"body": "Hello"},
    }


async def test_send_document_uploads_the_pdf_then_sends_it_by_media_id() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "MEDIA77"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.DOC"}]})

    wa_id = await client_with(httpx.MockTransport(handler)).send_document(
        "+919876543210", b"%PDF-1.4 data", "Q-2026-27-0001.pdf", "Your quotation"
    )
    assert wa_id == "wamid.DOC"
    upload, send = seen
    assert upload.url.path == "/v24.0/PNID1/media"
    assert b"%PDF-1.4 data" in upload.content and b'name="messaging_product"' in upload.content
    assert json.loads(send.content)["document"] == {
        "id": "MEDIA77",
        "filename": "Q-2026-27-0001.pdf",
        "caption": "Your quotation",
    }


@pytest.mark.parametrize(
    ("status", "permanent"), [(400, True), (401, True), (403, True), (429, False), (500, False)]
)
async def test_http_errors_are_marked_retryable_or_permanent(status: int, permanent: bool) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"type": "OAuthException", "code": 190}})

    with pytest.raises(WhatsAppError) as caught:
        await client_with(httpx.MockTransport(handler)).send_text("+919876543210", "Hi")
    assert caught.value.permanent is permanent
    assert caught.value.detail == "OAuthException 190"


async def test_a_network_failure_is_retryable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(WhatsAppError) as caught:
        await client_with(httpx.MockTransport(handler)).send_text("+919876543210", "Hi")
    assert not caught.value.permanent


async def test_a_response_without_a_message_id_is_an_error() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"messages": []}))
    with pytest.raises(WhatsAppError):
        await client_with(transport).send_text("+919876543210", "Hi")


async def test_download_media_follows_the_url_with_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "graph.facebook.com":
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.fbsbx.com/a.ogg",
                    "mime_type": "audio/ogg",
                    "file_size": 5,
                },
            )
        return httpx.Response(200, content=b"OggS1")

    audio, mime = await client_with(httpx.MockTransport(handler)).download_media("M1", 1000)
    assert (audio, mime) == (b"OggS1", "audio/ogg")
    assert all(r.headers["Authorization"] == "Bearer token-123" for r in seen)


async def test_download_media_refuses_large_files_and_non_https_urls() -> None:
    def too_big(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/a", "file_size": 5000})

    def insecure(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": "http://lookaside.fbsbx.com/a", "file_size": 5})

    for handler in (too_big, insecure):
        with pytest.raises(WhatsAppError) as caught:
            await client_with(httpx.MockTransport(handler)).download_media("M1", 1000)
        assert caught.value.permanent


async def test_download_media_enforces_the_size_cap_on_the_actual_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.facebook.com":
            return httpx.Response(
                200, json={"url": "https://lookaside.fbsbx.com/a", "file_size": 5}
            )
        return httpx.Response(200, content=b"x" * 2000)  # the metadata lied

    with pytest.raises(WhatsAppError):
        await client_with(httpx.MockTransport(handler)).download_media("M1", 1000)


# --- credentials at rest ---------------------------------------------------------------------


def test_credentials_round_trip_and_are_not_stored_in_clear() -> None:
    settings = Settings(app_env="test", secret_key="s" * 40)
    token = encrypt_credentials(settings, {"access_token": "EAAG-secret-token"})
    assert "EAAG-secret-token" not in token
    assert decrypt_credentials(settings, token) == {"access_token": "EAAG-secret-token"}


def test_credentials_need_the_same_key_to_decrypt() -> None:
    first = Settings(app_env="test", secret_key="a" * 40)
    second = Settings(app_env="test", secret_key="b" * 40)
    token = encrypt_credentials(first, {"access_token": "t"})
    with pytest.raises(ValueError, match="cannot be decrypted"):
        decrypt_credentials(second, token)


def test_an_explicit_encryption_key_is_used_and_required_in_prod() -> None:
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    settings = Settings(app_env="test", secret_key="s" * 40, credentials_encryption_key=key)
    assert decrypt_credentials(settings, encrypt_credentials(settings, {"a": "b"})) == {"a": "b"}
    with pytest.raises(ValidationError):
        Settings(app_env="prod", secret_key="k" * 40)
    assert Settings(app_env="prod", secret_key="k" * 40, credentials_encryption_key=key)


# --- the local speech model (a stand-in model: the real one downloads hundreds of MB) ------------


class _Segment:
    def __init__(self, text: str, avg_logprob: float) -> None:
        self.text, self.avg_logprob = text, avg_logprob


class _FakeWhisper:
    def __init__(self, segments: list[_Segment]) -> None:
        self._segments = segments

    def transcribe(self, audio: object, **_: object) -> tuple[object, object]:
        return iter(self._segments), type("Info", (), {"language": "hi"})()


async def test_whisper_transcriber_joins_segments_and_scores_them() -> None:
    transcriber = WhisperTranscriber("small")
    transcriber._model = _FakeWhisper([_Segment(" namaste ", -0.2), _Segment("kaise ho", -0.4)])  # noqa: SLF001
    result = await transcriber.transcribe(b"audio", "audio/ogg")
    assert (result.text, result.language) == ("namaste kaise ho", "hi")
    assert result.confidence == pytest.approx(math.exp(-0.3))


async def test_whisper_transcriber_reports_silence_as_empty_with_zero_confidence() -> None:
    transcriber = WhisperTranscriber("small")
    transcriber._model = _FakeWhisper([])  # noqa: SLF001
    result = await transcriber.transcribe(b"audio", "audio/ogg")
    assert (result.text, result.confidence) == ("", 0.0)


# --- where a voice note may be downloaded from ------------------------------------------------


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1", True),
        ("https://mmg.whatsapp.net/v/t62/x.enc", True),
        ("https://scontent.xx.fbcdn.net/x", True),
        ("https://FBSBX.com/x", True),  # case does not matter
        ("http://lookaside.fbsbx.com/x", False),  # plain http
        ("https://evilfbsbx.com/x", False),  # a look-alike
        ("https://fbsbx.com.evil.io/x", False),  # allowed name used as a prefix
        ("https://evil.io/fbsbx.com", False),  # allowed name in the path
        ("https://lookaside.fbsbx.com@evil.io/x", False),  # allowed name as user info
        ("https://169.254.169.254/latest/meta-data", False),  # a cloud metadata address
        ("https://localhost/x", False),
        ("https://cdn.example/x", False),
        ("not a url", False),
    ],
)
async def test_the_business_token_is_only_sent_to_metas_own_media_hosts(
    url: str, allowed: bool
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "graph.facebook.com":
            return httpx.Response(200, json={"url": url, "mime_type": "audio/ogg", "file_size": 3})
        return httpx.Response(200, content=b"abc")

    client = client_with(httpx.MockTransport(handler))
    if allowed:
        assert (await client.download_media("M1", 1000))[0] == b"abc"
    else:
        with pytest.raises(WhatsAppError) as refused:
            await client.download_media("M1", 1000)
        assert refused.value.permanent
        assert calls == ["graph.facebook.com"]  # the URL was never requested, so no token left


def test_the_allowed_hosts_come_from_a_setting_the_owner_can_widen() -> None:
    assert "fbsbx.com" in Settings(_env_file=None).media_host_list
    custom = Settings(_env_file=None, whatsapp_media_hosts=" Meta.example , other.example ,")
    assert custom.media_host_list == ("meta.example", "other.example")
