import io
import json
import uuid

import httpx
import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import Job
from app.db.session import SessionMaker
from app.jobs.handlers import build_handlers
from app.llm.embedder import FakeEmbedder
from app.llm.fake import FakeLLM
from tests.conftest import PASSWORD, bearer, register, unique_email

OWNER_ONLY_WRITES = [
    ("post", "/api/v1/catalog/items"),
    ("post", "/api/v1/catalog/import"),
    ("post", "/api/v1/documents"),
    ("post", "/api/v1/faqs"),
]


def xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


TEMPLATE_ROWS: list[list[object]] = [
    ["sku", "name", "aliases", "category", "unit", "price", "gst_rate", "stock_status", "Colour"],
    [
        "VC-100",
        "Visiting card",
        "business card; name card",
        "Printing",
        "per 100",
        250,
        18,
        "in stock",
        "white",
    ],
    ["FLEX-1", "Flex banner", "", "Printing", "per sq ft", "₹18/-", "12%", "", ""],
]


async def _upload_catalogue(
    client: httpx.AsyncClient, token: str, content: bytes
) -> httpx.Response:
    return await client.post(
        "/api/v1/catalog/import",
        files={"file": ("prices.xlsx", content, "application/octet-stream")},
        headers=bearer(token),
    )


async def _staff_token(client: httpx.AsyncClient, owner: str) -> str:
    email = unique_email()
    await client.post(
        "/api/v1/users",
        json={"email": email, "name": "S", "password": PASSWORD},
        headers=bearer(owner),
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return str(login.json()["access_token"])


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/catalog/items",
        "/api/v1/catalog/template.xlsx",
        "/api/v1/documents",
        "/api/v1/faqs",
        "/api/v1/knowledge-gaps",
        "/api/v1/conversations",
        "/api/v1/agent-runs",
    ],
)
async def test_reads_require_authentication(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401


@pytest.mark.parametrize(("method", "path"), OWNER_ONLY_WRITES)
async def test_writes_need_an_owner(client: httpx.AsyncClient, method: str, path: str) -> None:
    assert (await getattr(client, method)(path)).status_code == 401
    _, owner = await register(client)
    staff = await _staff_token(client, owner)
    assert (await getattr(client, method)(path, headers=bearer(staff))).status_code == 403


async def test_template_is_a_valid_spreadsheet_that_imports_cleanly(
    client: httpx.AsyncClient,
) -> None:
    _, token = await register(client)
    response = await client.get("/api/v1/catalog/template.xlsx", headers=bearer(token))
    assert response.status_code == 200 and "spreadsheetml" in response.headers["content-type"]
    headers = [c.value for c in load_workbook(io.BytesIO(response.content)).worksheets[0][1]]
    assert headers[:2] == ["sku", "name"] and "price" in headers
    preview = await _upload_catalogue(client, token, response.content)
    assert (
        preview.status_code == 201 and preview.json()["error_count"] == 0
    )  # the examples are valid


async def test_import_preview_then_commit_creates_items_and_queues_embedding(
    client: httpx.AsyncClient, sessionmaker: SessionMaker
) -> None:
    _, token = await register(client)
    created = await _upload_catalogue(client, token, xlsx(TEMPLATE_ROWS))
    assert created.status_code == 201
    preview = created.json()
    assert preview["missing_required"] == [] and preview["valid_count"] == 2
    assert preview["mapping"]["price"] == "price"

    commit = await client.post(
        f"/api/v1/catalog/import/{preview['job_id']}/commit", headers=bearer(token)
    )
    assert commit.json() == {"created": 2, "updated": 0, "skipped": 0}
    items = (await client.get("/api/v1/catalog/items", headers=bearer(token))).json()
    by_sku = {i["sku"]: i for i in items}
    assert by_sku["VC-100"]["base_price_paise"] == 25000
    assert by_sku["VC-100"]["aliases"] == ["business card", "name card"]
    assert by_sku["FLEX-1"]["base_price_paise"] == 1800 and by_sku["FLEX-1"]["gst_rate"] == 12
    assert by_sku["FLEX-1"]["stock_status"] == "na"

    again = await client.post(
        f"/api/v1/catalog/import/{preview['job_id']}/commit", headers=bearer(token)
    )
    assert again.status_code == 409  # cannot save the same import twice
    async with sessionmaker() as session:
        assert (
            await session.scalar(select(Job).where(Job.kind == "embed_catalog_items")) is not None
        )

    # re-importing the same file updates by SKU instead of duplicating
    second = (await _upload_catalogue(client, token, xlsx(TEMPLATE_ROWS))).json()
    result = await client.post(
        f"/api/v1/catalog/import/{second['job_id']}/commit", headers=bearer(token)
    )
    assert result.json() == {"created": 0, "updated": 2, "skipped": 0}


async def test_bad_rows_are_reported_and_skipped_never_guessed(client: httpx.AsyncClient) -> None:
    _, token = await register(client)
    rows = [
        ["name", "price", "gst_rate", "stock_status"],
        ["Good item", "1,200", 18, "in stock"],
        ["", 100, 18, ""],  # no name
        ["Bad price", "about 300", 18, ""],  # not a price
        ["Bad gst", 100, 7, ""],  # 7% is not a GST slab
        ["Half a paisa", "1.005", 18, ""],  # more than paisa precision
        ["Bad stock", 100, 18, "maybe"],
        ["Good two", 50, "", ""],  # missing GST defaults to 18
    ]
    preview = (await _upload_catalogue(client, token, xlsx(rows))).json()
    assert (preview["row_count"], preview["valid_count"], preview["error_count"]) == (7, 2, 5)
    problems = {r["row"]: r["errors"] for r in preview["rows"] if r["errors"]}
    assert set(problems) == {3, 4, 5, 6, 7}
    assert "price" in problems[4][0] and "GST" in problems[5][0]

    commit = await client.post(
        f"/api/v1/catalog/import/{preview['job_id']}/commit", headers=bearer(token)
    )
    assert commit.json() == {"created": 2, "updated": 0, "skipped": 5}
    names = {
        i["name"] for i in (await client.get("/api/v1/catalog/items", headers=bearer(token))).json()
    }
    assert names == {"Good item", "Good two"}


async def test_duplicate_skus_in_a_file_are_flagged(client: httpx.AsyncClient) -> None:
    _, token = await register(client)
    rows = [["sku", "name", "price"], ["A", "One", 10], ["a", "Two", 20]]
    preview = (await _upload_catalogue(client, token, xlsx(rows))).json()
    assert preview["valid_count"] == 1 and "duplicate SKU" in preview["rows"][-1]["errors"][0]


async def test_unfamiliar_columns_are_mapped_by_the_model_and_checked(
    client: httpx.AsyncClient, llm: FakeLLM
) -> None:
    _, token = await register(client)
    llm.add(
        json.dumps(
            {
                "mapping": {
                    "name": "Maal ka naam",
                    "price": "Bhav",
                    "category": "NOT A REAL COLUMN",  # the model invented a column: dropped
                }
            }
        )
    )
    rows = [["Maal ka naam", "Bhav"], ["Flex banner", 18]]
    preview = (await _upload_catalogue(client, token, xlsx(rows))).json()
    assert preview["mapping"] == {"name": "Maal ka naam", "price": "Bhav"}
    assert preview["valid_count"] == 1
    # catalogue data was only sent as headers and three sample rows, inside a delimited block
    user_turn = llm.calls[0][1][2].content
    assert "<catalogue>" in user_turn and "Maal ka naam" in user_turn


async def test_owner_can_fix_the_mapping_when_the_model_cannot(
    client: httpx.AsyncClient, llm: FakeLLM
) -> None:
    _, token = await register(client)
    llm.add("not json", "still not json")  # the mapper fails twice: no guess is made
    rows = [["Maal", "Bhav"], ["Flex", 18]]
    preview = (await _upload_catalogue(client, token, xlsx(rows))).json()
    assert preview["mapping"] == {} and preview["missing_required"] == ["name", "price"]
    blocked = await client.post(
        f"/api/v1/catalog/import/{preview['job_id']}/commit", headers=bearer(token)
    )
    assert blocked.status_code == 422

    fixed = await client.patch(
        f"/api/v1/catalog/import/{preview['job_id']}",
        json={"mapping": {"name": "Maal", "price": "Bhav"}},
        headers=bearer(token),
    )
    assert fixed.json()["valid_count"] == 1
    bad = await client.patch(
        f"/api/v1/catalog/import/{preview['job_id']}",
        json={"mapping": {"name": "Maal", "price": "Maal"}},  # one column for two fields
        headers=bearer(token),
    )
    assert bad.status_code == 422
    unknown = await client.patch(
        f"/api/v1/catalog/import/{preview['job_id']}",
        json={"mapping": {"nope": "Maal"}},
        headers=bearer(token),
    )
    assert unknown.status_code == 422


async def test_csv_files_import_too(client: httpx.AsyncClient) -> None:
    _, token = await register(client)
    csv_bytes = "sku;name;price\nA;Sticker;₹5/-\n".encode()
    response = await client.post(
        "/api/v1/catalog/import",
        files={"file": ("p.csv", csv_bytes, "text/csv")},
        headers=bearer(token),
    )
    assert response.status_code == 201 and response.json()["valid_count"] == 1


@pytest.mark.parametrize(
    "content",
    [b"", b"\x89PNG\r\n\x1a\n\x00\x00binary", b"PK\x03\x04\x00\x00not-an-xlsx"],
)
async def test_non_spreadsheets_are_rejected(client: httpx.AsyncClient, content: bytes) -> None:
    _, token = await register(client)
    assert (await _upload_catalogue(client, token, content)).status_code == 422


async def test_oversized_uploads_are_rejected(
    settings: Settings, client: httpx.AsyncClient
) -> None:
    _, token = await register(client)
    client._transport.app.state.settings = settings.model_copy(update={"max_upload_mb": 1})  # type: ignore[attr-defined]
    big = b"sku,name,price\n" + b"A,B,1\n" * 300_000
    response = await _upload_catalogue(client, token, big)
    assert response.status_code == 422 and "larger than 1 MB" in response.text


async def test_item_crud_validation_and_isolation(client: httpx.AsyncClient) -> None:
    _, a = await register(client)
    _, b = await register(client)
    body = {"sku": "S1", "name": "Sticker", "base_price_paise": 500, "gst_rate": 18}
    created = await client.post("/api/v1/catalog/items", json=body, headers=bearer(a))
    assert created.status_code == 201
    item_id = created.json()["id"]
    assert (
        await client.post("/api/v1/catalog/items", json=body, headers=bearer(a))
    ).status_code == 409
    for bad in ({"gst_rate": 7}, {"base_price_paise": -1}, {"base_price_paise": 1.5}, {"price": 5}):
        response = await client.post(
            "/api/v1/catalog/items", json={**body, "sku": "S2", **bad}, headers=bearer(a)
        )
        assert response.status_code == 422, bad

    updated = await client.patch(
        f"/api/v1/catalog/items/{item_id}",
        json={"base_price_paise": 650, "aliases": ["Label  Sticker"]},
        headers=bearer(a),
    )
    assert updated.json()["base_price_paise"] == 650 and updated.json()["aliases"] == [
        "label sticker"
    ]

    # tenant B can neither see, change nor delete A's item
    assert (await client.get("/api/v1/catalog/items", headers=bearer(b))).json() == []
    assert (
        await client.patch(
            f"/api/v1/catalog/items/{item_id}", json={"name": "x"}, headers=bearer(b)
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/catalog/items/{item_id}", headers=bearer(b))
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/catalog/items/{item_id}", headers=bearer(a))
    ).status_code == 204
    assert (await client.get("/api/v1/catalog/items", headers=bearer(a))).json() == []


async def test_import_jobs_are_tenant_isolated(client: httpx.AsyncClient) -> None:
    _, a = await register(client)
    _, b = await register(client)
    job = (await _upload_catalogue(client, a, xlsx(TEMPLATE_ROWS))).json()["job_id"]
    for call in (
        client.get(f"/api/v1/catalog/import/{job}", headers=bearer(b)),
        client.post(f"/api/v1/catalog/import/{job}/commit", headers=bearer(b)),
    ):
        assert (await call).status_code == 404


async def test_documents_upload_list_delete_and_validation(client: httpx.AsyncClient) -> None:
    _, a = await register(client)
    _, b = await register(client)
    text = b"# Returns\n\nAccepted within 7 days."
    uploaded = await client.post(
        "/api/v1/documents",
        files={"file": ("policy.txt", text, "text/plain")},
        data={"title": "Return policy"},
        headers=bearer(a),
    )
    assert uploaded.status_code == 201
    document = uploaded.json()
    assert (document["title"], document["status"], document["source_type"]) == (
        "Return policy",
        "pending",
        "txt",
    )
    assert len((await client.get("/api/v1/documents", headers=bearer(a))).json()) == 1
    assert (await client.get("/api/v1/documents", headers=bearer(b))).json() == []
    assert (
        await client.delete(f"/api/v1/documents/{document['id']}", headers=bearer(b))
    ).status_code == 404

    binary = await client.post(
        "/api/v1/documents",
        files={"file": ("x.pdf", b"\x00\x01\x02 not a pdf", "application/pdf")},  # name says pdf
        headers=bearer(a),
    )
    assert binary.status_code == 422
    assert (
        await client.delete(f"/api/v1/documents/{document['id']}", headers=bearer(a))
    ).status_code == 204
    assert (await client.get("/api/v1/documents", headers=bearer(a))).json() == []


async def test_faq_lifecycle_and_gap_answering(
    client: httpx.AsyncClient, sessionmaker: SessionMaker
) -> None:
    _, a = await register(client)
    _, b = await register(client)
    faq = (
        await client.post(
            "/api/v1/faqs",
            json={"question": "Do you deliver?", "answer": "Yes, within Surat."},
            headers=bearer(a),
        )
    ).json()
    listed = (await client.get("/api/v1/faqs", headers=bearer(a))).json()
    assert [(f["question"], f["answer"]) for f in listed] == [
        ("Do you deliver?", "Yes, within Surat.")
    ]
    updated = await client.put(
        f"/api/v1/faqs/{faq['id']}",
        json={"question": "Do you deliver?", "answer": "Yes, free above ₹500."},
        headers=bearer(a),
    )
    assert (
        updated.json()["answer"] == "Yes, free above ₹500."
        and updated.json()["status"] == "pending"
    )
    assert (await client.get("/api/v1/faqs", headers=bearer(b))).json() == []
    assert (
        await client.put(
            f"/api/v1/faqs/{faq['id']}", json={"question": "q", "answer": "a"}, headers=bearer(b)
        )
    ).status_code == 404

    # a gap logged by the bot (here directly) is answered into a new FAQ
    from app.repositories.gaps import KnowledgeGapRepository

    me = (await client.get("/api/v1/me", headers=bearer(a))).json()
    ctx = TenantContext.system(uuid.UUID(me["tenant"]["id"]))
    async with sessionmaker() as session:
        await KnowledgeGapRepository(session, ctx).record("Do you do lamination?", None)
        await KnowledgeGapRepository(session, ctx).record("do you do lamination", None)
        await session.commit()
    (gap,) = (await client.get("/api/v1/knowledge-gaps?status=open", headers=bearer(a))).json()
    assert (
        gap["occurrences"] == 2
        and (await client.get("/api/v1/knowledge-gaps", headers=bearer(b))).json() == []
    )
    answered = await client.post(
        f"/api/v1/knowledge-gaps/{gap['id']}/answer",
        json={"answer": "Yes, matt and gloss."},
        headers=bearer(a),
    )
    assert answered.json()["status"] == "answered"
    questions = {
        f["question"] for f in (await client.get("/api/v1/faqs", headers=bearer(a))).json()
    }
    assert "Do you do lamination?" in questions
    assert (
        await client.post(f"/api/v1/knowledge-gaps/{gap['id']}/ignore", headers=bearer(b))
    ).status_code == 404


async def test_playground_turn_end_to_end_through_the_worker(
    client: httpx.AsyncClient,
    settings: Settings,
    sessionmaker: SessionMaker,
    llm: FakeLLM,
) -> None:
    _, token = await register(client)
    _, other = await register(client)
    item = await client.post(
        "/api/v1/catalog/items",
        json={
            "sku": "VC-100",
            "name": "Visiting card",
            "base_price_paise": 25000,
            "unit": "per 100",
        },
        headers=bearer(token),
    )
    item_id = item.json()["id"]
    me = (await client.get("/api/v1/me", headers=bearer(token))).json()
    ctx = TenantContext.system(uuid.UUID(me["tenant"]["id"]))
    handlers = build_handlers(FakeEmbedder(), settings, llm)
    await handlers["embed_catalog_items"](sessionmaker, ctx, {})

    sent = await client.post(
        "/api/v1/playground/messages",
        json={"text": "visiting card ka rate?"},
        headers=bearer(token),
    )
    assert sent.status_code == 202
    conversation_id, message_id = sent.json()["conversation_id"], sent.json()["message_id"]
    async with (
        sessionmaker() as session
    ):  # debounced: due in the future, payload names only the chat
        job = await session.scalar(
            select(Job).where(Job.kind == "process_message", Job.tenant_id == ctx.tenant_id)
        )
        assert job is not None and job.payload == {"conversation_id": conversation_id}

    llm.add(
        json.dumps(
            {
                "intent": "pricing",
                "language": "hinglish",
                "confidence": 0.9,
                "mentioned_catalog_terms": ["visiting card"],
            }
        ),
        json.dumps(
            {
                "answer_points": ["Visiting cards are available."],
                "cited_item_ids": [item_id],
                "price_item_ids": [item_id],
                "grounded": True,
            }
        ),
        json.dumps({"reply": "Visiting card: ₹250.00 per 100 + 18% GST"}),
    )
    await handlers["process_message"](sessionmaker, ctx, job.payload)

    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=bearer(token))
    ).json()
    assert [m["direction"] for m in messages] == ["in", "out"]
    assert "₹250.00" in messages[1]["content"] and messages[1]["reply_to_id"] == message_id
    runs = (
        await client.get(f"/api/v1/agent-runs?message_id={message_id}", headers=bearer(token))
    ).json()
    assert [r["agent"] for r in runs] == ["router", "knowledge", "responder"]
    assert runs[1]["tool_calls"] and runs[0]["prompt_version"].startswith("router@")

    # nobody else can read the chat, the runs, or post into it
    assert (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=bearer(other))
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/agent-runs?message_id={message_id}", headers=bearer(other))
    ).json() == []
    assert (await client.get("/api/v1/conversations", headers=bearer(other))).json() == []
    intruder = await client.post(
        "/api/v1/playground/messages",
        json={"conversation_id": conversation_id, "text": "hi"},
        headers=bearer(other),
    )
    assert intruder.status_code == 404


async def test_playground_validates_input(client: httpx.AsyncClient) -> None:
    _, token = await register(client)
    for body in ({"text": ""}, {"text": "x" * 2001}, {}, {"text": "hi", "extra": 1}):
        response = await client.post(
            "/api/v1/playground/messages", json=body, headers=bearer(token)
        )
        assert response.status_code == 422, body
    missing = await client.post(
        "/api/v1/playground/messages",
        json={"conversation_id": str(uuid.uuid4()), "text": "hi"},
        headers=bearer(token),
    )
    assert missing.status_code == 404
