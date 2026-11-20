"""The audit trail: sensitive actions are recorded once, without customer text, for one business."""

import httpx
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import AuditEvent
from app.db.session import SessionMaker
from tests.conftest import PASSWORD, bearer, register, unique_email
from tests.helpers import login
from tests.integration.test_api_quotes import _new_quote
from tests.integration.test_customers import customer_of
from tests.integration.test_inbox import sent_quote
from tests.integration.test_whatsapp import connect


async def trail(client: httpx.AsyncClient, token: str) -> list[dict[str, str | None]]:
    response = await client.get("/api/v1/audit", headers=bearer(token))
    assert response.status_code == 200
    return list(response.json())


async def test_each_sensitive_action_is_recorded_with_who_did_it(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    _, token = await register(client)
    h = bearer(token)
    me = (await client.get("/api/v1/me", headers=h)).json()["user"]
    assert await trail(client, token) == []

    await connect(client, token, "110000000000077")
    await client.delete("/api/v1/channels/whatsapp", headers=h)
    staff_email = unique_email()
    created = await client.post(
        "/api/v1/users",
        json={"email": staff_email, "name": "Staff", "password": PASSWORD, "role": "staff"},
        headers=h,
    )
    staff_id = created.json()["id"]
    for active in (False, False, True):  # the repeat changes nothing, so records nothing
        await client.patch(f"/api/v1/users/{staff_id}", json={"is_active": active}, headers=h)
    await client.patch(f"/api/v1/users/{staff_id}", json={"name": "Renamed"}, headers=h)

    edited = await _new_quote(client, sessionmaker, settings, token)
    number = (await client.get(f"/api/v1/quotes/{edited}", headers=h)).json()["quote_number"]
    await client.patch(f"/api/v1/quotes/{edited}", json={"buyer_state_code": "27"}, headers=h)
    await client.post(f"/api/v1/quotes/{edited}/approve", headers=h)
    rejected = await _new_quote(client, sessionmaker, settings, token)
    rejected_number = (await client.get(f"/api/v1/quotes/{rejected}", headers=h)).json()[
        "quote_number"
    ]
    await client.post(f"/api/v1/quotes/{rejected}/reject", headers=h)
    # A refused action leaves no trace: it did not happen.
    assert (await client.post(f"/api/v1/quotes/{edited}/approve", headers=h)).status_code == 409

    events = await trail(client, token)
    assert [(e["action"], e["target"]) for e in reversed(events)] == [
        ("whatsapp_connected", "110000000000077"),
        ("whatsapp_disconnected", None),
        ("user_created", staff_id),
        ("user_deactivated", staff_id),
        ("user_reactivated", staff_id),
        ("quote_edited", number),
        ("quote_approved", number),
        ("quote_rejected", rejected_number),
    ]
    assert {e["actor"] for e in events} == {me["name"]}


async def test_erasing_a_customer_is_recorded_without_keeping_what_they_said(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    _, conversation, _, email = await sent_quote(sessionmaker, settings, days_ago=1)
    token = await login(client, email)
    target = await customer_of(sessionmaker, conversation)
    await client.delete(f"/api/v1/customers/{target}", headers=bearer(token))

    (event,) = [e for e in await trail(client, token) if e["action"] == "customer_erased"]
    assert event["target"] == str(target)
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(AuditEvent)))
    everything = " ".join(f"{r.action} {r.target}" for r in rows).lower()
    assert "visiting cards" not in everything and "matt" not in everything


async def test_the_trail_is_owner_only_scoped_to_one_business_and_bounded(
    client: httpx.AsyncClient,
) -> None:
    _, owner = await register(client)
    _, other = await register(client)
    await connect(client, owner, "110000000000088")
    staff_email = unique_email()
    await client.post(
        "/api/v1/users",
        json={"email": staff_email, "name": "S", "password": PASSWORD, "role": "staff"},
        headers=bearer(owner),
    )
    staff = await login(client, staff_email)

    assert (await client.get("/api/v1/audit")).status_code == 401
    assert (await client.get("/api/v1/audit", headers=bearer(staff))).status_code == 403
    assert await trail(client, other) == []  # another business sees nothing of this one
    assert len(await trail(client, owner)) == 2
    for bad in ("0", "201", "abc"):
        response = await client.get(f"/api/v1/audit?limit={bad}", headers=bearer(owner))
        assert response.status_code == 422
    one = await client.get("/api/v1/audit?limit=1", headers=bearer(owner))
    assert len(one.json()) == 1
