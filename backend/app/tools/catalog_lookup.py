from app.llm import Embedder
from app.pricing.catalog import catalog_price
from app.repositories.identity import TenantRepository
from app.repositories.search import SearchRepository
from app.schemas.knowledge import Fact, SearchResults
from app.tools.query import normalize_query


class CatalogLookup:
    def __init__(self, repository: SearchRepository, embedder: Embedder) -> None:
        self.repository, self.embedder = repository, embedder

    async def lookup_catalog(self, query: str, k: int = 5) -> SearchResults:
        normalized = normalize_query(query, catalog=True)
        if not normalized:
            return SearchResults(facts=[])
        vector = (await self.embedder.embed([normalized]))[0]
        catalogs = await self.repository.catalog(normalized, vector, min(max(k, 1), 10))
        facts = []
        for catalog in catalogs:
            price = catalog_price(catalog)
            text = (
                f"{catalog.name}: {price.formatted} per {catalog.unit}. "
                f"GST {catalog.gst_rate}%. Stock: {catalog.stock_status.value}. "
                f"{catalog.description}"
            ).strip()
            facts.append(
                Fact(ref="catalog:" + str(catalog.id), kind="catalog", text=text, price=price)
            )
        return SearchResults(facts=facts)


async def get_business_info(repository: TenantRepository) -> SearchResults:
    tenant = await repository.get()
    settings = await repository.settings()
    text = tenant.name
    if tenant.address:
        text += ". Address: " + tenant.address
    if settings.business_hours:
        text += ". Business hours: " + "; ".join(
            str(key) + ": " + str(value) for key, value in settings.business_hours.items()
        )
    return SearchResults(
        facts=[Fact(ref="business:" + str(tenant.id), kind="business", text=text, price=None)]
    )
