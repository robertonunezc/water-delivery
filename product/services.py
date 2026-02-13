import logging
from typing import Dict, List
from django.db import transaction
from clients.models import Client
from .models import Product, ProductClientPrice

logger = logging.getLogger(__name__)


def ensure_client_product_prices(client: Client) -> Dict[str, object]:
    """Create missing ProductClientPrice rows for the given client using Product.price."""
    created_products: List[str] = []
    existing_products: List[str] = []

    with transaction.atomic():
        for product in Product.objects.all().only("id", "price", "name"):
            _, created = ProductClientPrice.objects.get_or_create(
                product=product,
                client=client,
                price=product.price,
            )
            if created:
                created_products.append(product.name)
            else:
                existing_products.append(product.name)

    summary: Dict[str, object] = {
        "created_count": len(created_products),
        "existing_count": len(existing_products),
        "created_products": created_products,
        "existing_products": existing_products,
    }

    logger.info(
        "Ensured client product prices", extra={
            "client_id": client.id,
            "client_name": client.name,
            "created_count": summary["created_count"],
            "existing_count": summary["existing_count"],
            "created_products": created_products,
        }
    )

    return summary
