from datetime import UTC, datetime, timedelta

from app.llm import FakeEmbedder
from app.repositories.catalog import CatalogRepository
from app.repositories.pricing_rules import PricingRuleRepository
from app.schemas.catalog import CatalogInput
from app.schemas.pricing import PricingRuleInput
from tests.integration.test_workspace import owner


async def test_pricing_rule_auth_scope_validation_and_effective_dates(client, sessions):
    a, ctx_a, _ = await owner(client)
    b, ctx_b, _ = await owner(client)
    async with sessions() as session:
        catalog = await CatalogRepository(session, ctx_a).upsert(
            CatalogInput(sku="CARD", name="Cards", base_price_paise=45000),
            (await FakeEmbedder().embed(["Cards"]))[0],
        )
        catalog_id = str(catalog.id)
        await session.commit()
    path = "/api/v1/catalog/pricing-rules"
    body = {
        "catalog_item_id": catalog_id,
        "rule": {
            "rule_type": "addon",
            "option": "sides",
            "value": "double-sided",
            "amount_paise": 10000,
            "per_unit": True,
        },
    }
    assert (await client.get(path)).status_code == 401
    assert (await client.post(path, json=body)).status_code == 401
    assert (await client.post(path, headers=b, json=body)).status_code == 404
    created = await client.post(path, headers=a, json=body)
    assert created.status_code == 201
    rule_id = created.json()["id"]
    assert (await client.get(path, headers=b)).json() == []
    assert (await client.delete(path + "/" + rule_id, headers=b)).status_code == 404
    invalid = {**body, "rule": {**body["rule"], "amount_paise": -1}}
    assert (await client.post(path, headers=a, json=invalid)).status_code == 422
    now = datetime.now(UTC)
    async with sessions() as session:
        repo = PricingRuleRepository(session, ctx_a)
        for start, end in ((now + timedelta(days=1), None), (None, now - timedelta(days=1))):
            await repo.add(
                PricingRuleInput.model_validate({**body, "active_from": start, "active_to": end})
            )
        assert (
            len(await repo.applicable(await CatalogRepository(session, ctx_a).get(catalog.id), now))
            == 1
        )
        assert await PricingRuleRepository(session, ctx_b).list() == []
        await session.commit()
    assert (await client.delete(path + "/" + rule_id, headers=a)).status_code == 204
