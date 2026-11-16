import uuid
from decimal import Decimal as D

import httpx
import pytest

from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import Channel
from app.db.session import SessionMaker
from app.orchestrator.leads import sync_lead
from app.repositories.catalog import CatalogRepository, CatalogRow
from app.repositories.chat import ChatRepository
from app.services.quotes import ProposedLine, QuoteService
from tests.conftest import PASSWORD, bearer, register, unique_email


async def _context(client: httpx.AsyncClient, token: str) -> TenantContext:
    me = (await client.get("/api/v1/me", headers=bearer(token))).json()
    return TenantContext.system(uuid.UUID(me["tenant"]["id"]))


async def _staff(client: httpx.AsyncClient, owner: str) -> str:
    email = unique_email()
    await client.post(
        "/api/v1/users",
        json={"email": email, "name": "S", "password": PASSWORD},
        headers=bearer(owner),
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return str(login.json()["access_token"])


async def _new_quote(
    client: httpx.AsyncClient,
    sessionmaker: SessionMaker,
    settings: Settings,
    token: str,
    *,
    unpriced: bool = False,
) -> str:
    """A pending quote: 5 units of a Rs 250 item, optionally plus an unpriced line."""
    ctx = await _context(client, token)
    async with sessionmaker() as session:
        item = await CatalogRepository(session, ctx).add_one(
            CatalogRow(
                sku=f"S-{uuid.uuid4().hex[:6]}",
                name="Sticker",
                base_price_paise=25000,
                unit="per 100",
            )
        )
        conversation = await ChatRepository(session, ctx).start_conversation(
            Channel.PLAYGROUND, "Asha"
        )
        lead = await sync_lead(session, ctx, conversation)
        lines = [ProposedLine("Sticker", item.id, D(500))]
        if unpriced:
            lines.append(ProposedLine("Mystery work", None, D(1)))
        quote, _ = await QuoteService(session, ctx, settings).create(lead.id, lines)
        await session.commit()
        return str(quote.id)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/quotes",
        f"/api/v1/quotes/{uuid.uuid4()}",
        f"/api/v1/quotes/{uuid.uuid4()}/pdf",
        "/api/v1/tenant",
        "/api/v1/catalog/pricing-rules",
        "/api/v1/requirement-schemas",
    ],
)
async def test_reads_require_authentication(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401


# --- business profile ------------------------------------------------------------------------


async def test_profile_validation_and_the_gstin_decides_the_state(
    client: httpx.AsyncClient,
) -> None:
    _, token = await register(client)
    h = bearer(token)
    before = (await client.get("/api/v1/tenant", headers=h)).json()
    assert before["gstin"] is None and before["quote_validity_days"] == 7

    ok = await client.put(
        "/api/v1/tenant",
        json={
            "gstin": "24abcde1234f1z5",
            "address": "Ring Road, Surat",
            "phone": "+91 90000 00001",
            "quote_terms": "50% advance",
            "quote_validity_days": 14,
        },
        headers=h,
    )
    assert ok.status_code == 200
    body = ok.json()
    assert (body["gstin"], body["state_code"], body["quote_validity_days"]) == (
        "24ABCDE1234F1Z5",
        "24",
        14,
    )
    assert body["name"] == before["name"]  # fields not sent are left alone

    for bad in (
        {"gstin": "NOTAGSTIN"},
        {"gstin": "24ABCDE1234F1Z5", "state_code": "27"},  # GSTIN starts with 24
        {"state_code": "99"},
        {"phone": "call me"},
        {"quote_validity_days": 0},
        {"quote_validity_days": 400},
        {"quote_terms": "x" * 2001},
        {"name": ""},
        {"plan": "free"},  # unknown field
    ):
        assert (await client.put("/api/v1/tenant", json=bad, headers=h)).status_code == 422, bad

    cleared = await client.put("/api/v1/tenant", json={"gstin": None, "address": None}, headers=h)
    assert cleared.json()["gstin"] is None and cleared.json()["address"] is None
    kept = await client.put("/api/v1/tenant", json={"name": None}, headers=h)
    assert kept.json()["name"] == before["name"]  # a name cannot be blanked


async def test_profile_is_owner_only_to_change_and_tenant_isolated(
    client: httpx.AsyncClient,
) -> None:
    _, a = await register(client)
    _, b = await register(client)
    staff = await _staff(client, a)
    assert (await client.get("/api/v1/tenant", headers=bearer(staff))).status_code == 200
    assert (
        await client.put("/api/v1/tenant", json={"address": "x"}, headers=bearer(staff))
    ).status_code == 403
    await client.put("/api/v1/tenant", json={"address": "A's shop"}, headers=bearer(a))
    assert (await client.get("/api/v1/tenant", headers=bearer(b))).json()["address"] is None


# --- pricing rules ---------------------------------------------------------------------------


async def _item(client: httpx.AsyncClient, token: str) -> str:
    created = await client.post(
        "/api/v1/catalog/items",
        json={"sku": uuid.uuid4().hex[:8], "name": "Card", "base_price_paise": 25000},
        headers=bearer(token),
    )
    return str(created.json()["id"])


async def test_pricing_rules_validation_ownership_and_isolation(client: httpx.AsyncClient) -> None:
    _, a = await register(client)
    _, b = await register(client)
    item = await _item(client, a)
    url = "/api/v1/catalog/pricing-rules"

    tier = await client.post(
        url,
        json={
            "rule_type": "qty_tier",
            "catalog_item_id": item,
            "tiers": [
                {"min_qty": "5", "unit_price_paise": 23500},
                {"min_qty": "10", "discount_pct": "12.5"},
            ],
        },
        headers=bearer(a),
    )
    assert tier.status_code == 201
    assert tier.json()["params"]["tiers"][1] == {
        "min_qty": "10",
        "unit_price_paise": None,
        "discount_pct": "12.5",
    }
    addon = await client.post(
        url,
        json={
            "rule_type": "addon",
            "category": "Cards",
            "addon": {"code": "LAM-1", "name": "Lamination", "price_paise": 4500},
        },
        headers=bearer(a),
    )
    minimum = await client.post(
        url,
        json={"rule_type": "min_order", "catalog_item_id": item, "min_qty": "2"},
        headers=bearer(a),
    )
    assert addon.status_code == minimum.status_code == 201 and addon.json()["params"]["per_unit"]

    bad_bodies = [
        {"rule_type": "qty_tier", "tiers": [{"min_qty": "5", "unit_price_paise": 1}]},  # no target
        {
            "rule_type": "qty_tier",
            "catalog_item_id": item,
            "category": "x",
            "tiers": [{"min_qty": "5", "unit_price_paise": 1}],
        },  # two targets
        {"rule_type": "qty_tier", "catalog_item_id": item},  # no tiers
        {"rule_type": "qty_tier", "catalog_item_id": item, "tiers": [{"min_qty": "5"}]},
        {
            "rule_type": "qty_tier",
            "catalog_item_id": item,
            "tiers": [{"min_qty": "5", "unit_price_paise": 1, "discount_pct": "5"}],
        },
        {
            "rule_type": "qty_tier",
            "catalog_item_id": item,
            "tiers": [{"min_qty": "5", "discount_pct": "101"}],
        },
        {
            "rule_type": "qty_tier",
            "catalog_item_id": item,
            "tiers": [{"min_qty": "0", "unit_price_paise": 1}],
        },
        {
            "rule_type": "addon",
            "catalog_item_id": item,
            "addon": {"code": "bad code!", "name": "x", "price_paise": 1},
        },
        {
            "rule_type": "addon",
            "catalog_item_id": item,
            "addon": {"code": "A", "name": "x", "price_paise": -1},
        },
        {"rule_type": "addon", "catalog_item_id": item, "min_qty": "2"},  # wrong details
        {
            "rule_type": "min_order",
            "catalog_item_id": item,
            "min_qty": "2",
            "addon": {"code": "A", "name": "x", "price_paise": 1},
        },  # two kinds at once
        {"rule_type": "surcharge", "catalog_item_id": item},
    ]
    for body in bad_bodies:
        assert (await client.post(url, json=body, headers=bearer(a))).status_code == 422, body

    assert len((await client.get(url, headers=bearer(a))).json()) == 3
    assert (await client.get(url, headers=bearer(b))).json() == []
    foreign = await client.post(
        url,
        json={"rule_type": "min_order", "catalog_item_id": item, "min_qty": "2"},
        headers=bearer(b),
    )
    assert foreign.status_code == 404  # B cannot attach a rule to A's item
    rule_id = tier.json()["id"]
    assert (await client.delete(f"{url}/{rule_id}", headers=bearer(b))).status_code == 404
    staff = await _staff(client, a)
    assert (await client.delete(f"{url}/{rule_id}", headers=bearer(staff))).status_code == 403
    assert (await client.delete(f"{url}/{rule_id}", headers=bearer(a))).status_code == 204
    assert (await client.delete(f"{url}/{rule_id}", headers=bearer(a))).status_code == 404


# --- requirement schemas ---------------------------------------------------------------------

GOOD_SCHEMA = {
    "json_schema": {
        "properties": {
            "item_type": {"type": "string"},
            "quantity": {"type": "integer"},
            "sides": {"type": "string", "enum": ["single", "double"]},
        },
        "required": ["item_type", "quantity"],
    },
    "defaults": {"sides": "double"},
    "question_hints": {"quantity": "How many?"},
}


async def test_requirement_schemas_are_validated_owner_only_and_isolated(
    client: httpx.AsyncClient,
) -> None:
    _, a = await register(client)
    _, b = await register(client)
    url = "/api/v1/requirement-schemas"
    saved = await client.put(f"{url}/printing", json=GOOD_SCHEMA, headers=bearer(a))
    assert saved.status_code == 200 and saved.json()["defaults"] == {"sides": "double"}
    again = await client.put(f"{url}/printing", json=GOOD_SCHEMA, headers=bearer(a))
    assert again.status_code == 200  # saving the same category replaces it
    assert len((await client.get(url, headers=bearer(a))).json()) == 1
    assert (await client.get(url, headers=bearer(b))).json() == []

    def with_schema(**changes: object) -> dict[str, object]:
        return {**GOOD_SCHEMA, **changes}

    props = GOOD_SCHEMA["json_schema"]["properties"]  # type: ignore[index]
    for bad in (
        with_schema(json_schema={"properties": {}}),
        with_schema(json_schema={"properties": {"Bad Name": {"type": "string"}}}),
        with_schema(json_schema={"properties": {"x": {"type": "object"}}}),
        with_schema(json_schema={"properties": props, "required": ["ghost"]}),
        with_schema(json_schema="nonsense"),
        with_schema(defaults={"sides": "triple"}),  # not an allowed option
        with_schema(defaults={"unknown_slot": "x"}),
        with_schema(question_hints={"ghost": "?"}),
        {**GOOD_SCHEMA, "extra": 1},
    ):
        assert (await client.put(f"{url}/printing", json=bad, headers=bearer(a))).status_code == 422
    staff = await _staff(client, a)
    assert (
        await client.put(f"{url}/x", json=GOOD_SCHEMA, headers=bearer(staff))
    ).status_code == 403
    assert (await client.get(url, headers=bearer(staff))).status_code == 200


# --- quotes ----------------------------------------------------------------------------------


async def test_quote_review_edit_approve_and_download(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    _, token = await register(client)
    h = bearer(token)
    # The seller's state decides inter- vs intra-state tax; without one, tax is CGST + SGST.
    await client.put("/api/v1/tenant", json={"gstin": "24ABCDE1234F1Z5"}, headers=h)
    quote_id = await _new_quote(client, sessionmaker, settings, token)

    listed = (await client.get("/api/v1/quotes?status=pending_approval", headers=h)).json()
    assert [q["id"] for q in listed] == [quote_id]
    assert listed[0]["customer_name"] == "Asha" and listed[0]["unpriced_lines"] == 0
    assert (await client.get("/api/v1/quotes?status=sent", headers=h)).json() == []
    assert (await client.get("/api/v1/quotes?status=bogus", headers=h)).status_code == 422

    detail = (await client.get(f"/api/v1/quotes/{quote_id}", headers=h)).json()
    assert detail["status"] == "pending_approval" and len(detail["items"]) == 1
    # 5 units x Rs 250 = 1,250 ; GST 18% = 225 ; total 1,475
    assert (detail["subtotal_paise"], detail["cgst_paise"], detail["total_paise"]) == (
        125000,
        11250,
        147500,
    )
    assert detail["tax_groups"] == [
        {
            "gst_rate": 18,
            "taxable_paise": 125000,
            "cgst_paise": 11250,
            "sgst_paise": 11250,
            "igst_paise": 0,
        }
    ]

    line = detail["items"][0]["id"]
    edited = await client.patch(
        f"/api/v1/quotes/{quote_id}",
        json={"items": [{"id": line, "discount_paise": 25000}], "buyer_state_code": "27"},
        headers=h,
    )
    assert edited.status_code == 200
    assert (edited.json()["igst_paise"], edited.json()["total_paise"]) == (18000, 118000)
    # a client cannot write totals or statuses directly
    for forged in (
        {"total_paise": 1},
        {"status": "sent"},
        {"items": [{"id": line, "line_total_paise": 1}]},
    ):
        assert (
            await client.patch(f"/api/v1/quotes/{quote_id}", json=forged, headers=h)
        ).status_code == 422
    for bad in (
        {"items": [{"id": line, "qty": 0}]},
        {"items": [{"id": line, "qty": "-2"}]},
        {"items": [{"id": line, "qty": "1.0005"}]},
        {"items": [{"id": line, "unit_price_paise": -1}]},
        {
            "items": [{"id": line, "discount_paise": 10**9}]
        },  # larger than the line: the engine refuses
        {"buyer_state_code": "ZZ"},
    ):
        assert (
            await client.patch(f"/api/v1/quotes/{quote_id}", json=bad, headers=h)
        ).status_code == 422, bad

    staff = await _staff(client, token)
    assert (
        await client.post(f"/api/v1/quotes/{quote_id}/approve", headers=bearer(staff))
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/quotes/{quote_id}", headers=bearer(staff))
    ).status_code == 200

    pdf = await client.get(f"/api/v1/quotes/{quote_id}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-type"] == "application/pdf"
    assert "/" not in pdf.headers["content-disposition"].split("filename=")[1]

    approved = await client.post(f"/api/v1/quotes/{quote_id}/approve", headers=h)
    assert approved.status_code == 200 and approved.json()["status"] == "sent"
    assert approved.json()["sent_at"] is not None
    assert (await client.post(f"/api/v1/quotes/{quote_id}/approve", headers=h)).status_code == 409
    assert (await client.patch(f"/api/v1/quotes/{quote_id}", json={}, headers=h)).status_code == 409
    accepted = await client.post(f"/api/v1/quotes/{quote_id}/mark-accepted", headers=h)
    assert accepted.json()["status"] == "accepted"


async def test_unpriced_lines_block_approval_until_the_owner_prices_them(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    _, token = await register(client)
    h = bearer(token)
    quote_id = await _new_quote(client, sessionmaker, settings, token, unpriced=True)
    listed = (await client.get("/api/v1/quotes", headers=h)).json()
    assert listed[0]["unpriced_lines"] == 1
    detail = (await client.get(f"/api/v1/quotes/{quote_id}", headers=h)).json()
    mystery = next(i for i in detail["items"] if i["needs_owner_pricing"])
    assert mystery["unit_price_paise"] == 0
    blocked = await client.post(f"/api/v1/quotes/{quote_id}/approve", headers=h)
    assert blocked.status_code == 409 and "Price every line" in blocked.text
    await client.patch(
        f"/api/v1/quotes/{quote_id}",
        json={"items": [{"id": mystery["id"], "unit_price_paise": 50000}]},
        headers=h,
    )
    assert (await client.post(f"/api/v1/quotes/{quote_id}/approve", headers=h)).status_code == 200


async def test_reject_and_state_machine(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    _, token = await register(client)
    h = bearer(token)
    quote_id = await _new_quote(client, sessionmaker, settings, token)
    assert (
        await client.post(f"/api/v1/quotes/{quote_id}/mark-accepted", headers=h)
    ).status_code == 409
    rejected = await client.post(f"/api/v1/quotes/{quote_id}/reject", headers=h)
    assert rejected.json()["status"] == "rejected"
    for action in ("approve", "reject", "mark-accepted"):
        assert (
            await client.post(f"/api/v1/quotes/{quote_id}/{action}", headers=h)
        ).status_code == 409


async def test_quotes_are_tenant_isolated_over_http(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    _, a = await register(client)
    _, b = await register(client)
    quote_id = await _new_quote(client, sessionmaker, settings, a)
    hb = bearer(b)
    assert (await client.get("/api/v1/quotes", headers=hb)).json() == []
    for method, path in (
        ("get", f"/api/v1/quotes/{quote_id}"),
        ("get", f"/api/v1/quotes/{quote_id}/pdf"),
        ("patch", f"/api/v1/quotes/{quote_id}"),
        ("post", f"/api/v1/quotes/{quote_id}/approve"),
        ("post", f"/api/v1/quotes/{quote_id}/reject"),
        ("post", f"/api/v1/quotes/{quote_id}/mark-accepted"),
    ):
        kwargs = {"json": {}} if method == "patch" else {}
        response = await getattr(client, method)(path, headers=hb, **kwargs)
        assert response.status_code == 404, (method, path)
    still = await client.get(f"/api/v1/quotes/{quote_id}", headers=bearer(a))
    assert still.json()["status"] == "pending_approval"
