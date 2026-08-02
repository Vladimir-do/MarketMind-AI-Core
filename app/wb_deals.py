from app.parsers.base import ProductData


def find_wb_deals(
    products: list[ProductData],
    *,
    min_discount_pct: int = 30,
    limit: int = 10,
) -> list[dict]:
    deals = []
    for product in products:
        if product.price is None or product.old_price is None:
            continue
        if product.old_price <= 0 or product.old_price <= product.price:
            continue

        discount_pct = product.discount_pct
        if discount_pct is None:
            discount_pct = round((product.old_price - product.price) / product.old_price * 100)
        if discount_pct < min_discount_pct:
            continue

        deals.append(
            {
                "name": product.name,
                "url": product.url,
                "price": product.price,
                "old_price": product.old_price,
                "discount_pct": discount_pct,
                "availability": product.availability,
            }
        )

    deals.sort(key=lambda item: (-item["discount_pct"], item["price"]))
    return deals[:limit]
