from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import yaml
from PIL import Image
from pypdf import PdfReader
from redis.asyncio import Redis

from app.core.security import issue_token
from app.llm import FakeEmbedder, FakeLLM
from app.llm.offline import agent_response
from app.orchestrator.locks import RedisConversationLock
from app.orchestrator.pipeline import ConversationOrchestrator
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.identity import UserRepository
from seeds.demo import seed_demo
from tests.integration.test_workspace import FakeQueue, owner


async def test_phase2_quote_conversations_owner_approval_and_widget_pdf(
    client, sessions, redis_url, tmp_path
):
    tenants = await seed_demo(sessions, FakeEmbedder(), "synthetic-unused-hash")
    app = client._transport.app
    app.state.jobs = FakeQueue()
    app.state.settings.storage_dir = str(tmp_path)
    redis = Redis.from_url(redis_url)
    app.state.redis = redis
    other, _, _ = await owner(client)
    cases = yaml.safe_load(
        (Path(__file__).parent / "phase2_conversations.yaml").read_text(encoding="utf-8")
    )
    try:
        for case in cases:
            ctx = tenants[case["tenant"]]
            async with sessions() as session:
                user = (await UserRepository(session, ctx).list())[0]
                token, _ = issue_token(app.state.settings, user.id, ctx.tenant_id, "access")
            auth = {"Authorization": "Bearer " + token}
            profile = {
                "name": "Demo Business",
                "gstin": "24AAAAA0000A1Z5",
                "state_code": "24",
                "address": "Demo Market, Ahmedabad",
            }
            assert (
                await client.put("/api/v1/tenant/quote-profile", headers=auth, json=profile)
            ).status_code == 200
            image = BytesIO()
            Image.new("RGB", (120, 60), "#196a59").save(image, format="PNG")
            assert (
                await client.post(
                    "/api/v1/tenant/logo",
                    headers=auth,
                    files={"file": ("logo.png", image.getvalue(), "image/png")},
                )
            ).status_code == 201
            widget = (await client.post("/api/v1/playground/session", headers=auth)).json()
            widget_auth = {"Authorization": "Bearer " + widget["token"]}
            conversation_id = UUID(widget["conversation_id"])
            fake = FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=agent_response)
            last_message = None
            for index, question in enumerate(case["turns"]):
                sent = await client.post(
                    "/api/v1/widget/messages",
                    headers=widget_auth,
                    json={
                        "session_id": widget["session_id"],
                        "external_id": str(uuid4()),
                        "content": question,
                    },
                )
                assert sent.status_code == 202
                async with sessions() as session:
                    reply = await ConversationOrchestrator(
                        session,
                        ctx,
                        fake,
                        FakeEmbedder(),
                        RedisConversationLock(redis),
                        app.state.settings,
                    ).process(conversation_id)
                    assert reply is not None
                    if index == 0:
                        assert 1 <= reply.content.count("?") <= 2
                    else:
                        assert "team to review" in reply.content
                last_message = sent.json()["id"]
            quotes = (
                await client.get("/api/v1/quotes?status=pending_approval", headers=auth)
            ).json()
            quote = next(
                quote for quote in quotes if quote["conversation_id"] == str(conversation_id)
            )
            for key in ("subtotal_paise", "cgst_paise", "sgst_paise", "total_paise"):
                assert quote["totals"][key] == case[key]
            assert not any(line["needs_owner_pricing"] for line in quote["lines"])
            url = f"/api/v1/quotes/{quote['id']}/approve"
            body = {"expected_version": quote["version"]}
            assert (
                await client.get(f"/api/v1/widget/quotes/{quote['id']}/pdf", headers=widget_auth)
            ).status_code == 404
            assert (await client.post(url, json=body)).status_code == 401
            assert (await client.post(url, headers=other, json=body)).status_code == 404
            approved = await client.post(url, headers=auth, json=body)
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "sent"
            assert (await client.post(url, headers=auth, json=body)).status_code == 200
            history = (
                await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=auth)
            ).json()
            assert (
                sum(
                    any(a.get("quote_id") == quote["id"] for a in message["attachments"])
                    for message in history
                )
                == 1
            )
            pdf = await client.get(f"/api/v1/widget/quotes/{quote['id']}/pdf", headers=widget_auth)
            assert pdf.status_code == 200
            reader = PdfReader(BytesIO(pdf.content))
            text = "\n".join(page.extract_text() for page in reader.pages)
            assert case["pdf_amount"] in text and "24AAAAA0000A1Z5" in text
            assert len(reader.pages[0].images) == 1
            different = (await client.post("/api/v1/playground/session", headers=auth)).json()
            assert (
                await client.get(
                    f"/api/v1/widget/quotes/{quote['id']}/pdf",
                    headers={"Authorization": "Bearer " + different["token"]},
                )
            ).status_code == 404
            assert (await client.get(f"/api/v1/widget/quotes/{quote['id']}/pdf")).status_code == 401
            assert last_message is not None
            async with sessions() as session:
                assert (
                    await ConversationOrchestrator(
                        session,
                        ctx,
                        fake,
                        FakeEmbedder(),
                        RedisConversationLock(redis),
                        app.state.settings,
                    ).process(conversation_id)
                    is None
                )
    finally:
        await redis.aclose()
