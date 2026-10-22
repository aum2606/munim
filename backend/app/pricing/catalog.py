from app.db.models.knowledge import CatalogItem
from app.pricing.inr import format_inr
from app.schemas.knowledge import PriceRef


def catalog_price(catalog: CatalogItem) -> PriceRef:
    return PriceRef(
        catalog_id=catalog.id,
        sku=catalog.sku,
        paise=catalog.base_price_paise,
        formatted=format_inr(catalog.base_price_paise),
    )
