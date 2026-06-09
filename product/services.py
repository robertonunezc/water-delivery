import logging
from typing import Dict, List, Optional
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


def ensure_product_for_all_clients(product: Product, user=None) -> Dict[str, object]:
    """Create missing ProductClientPrice rows for the given product across all clients."""
    created_clients: List[str] = []
    existing_clients: List[str] = []

    with transaction.atomic():
        for client in Client.objects.all().only("id", "name"):
            _, created = ProductClientPrice.objects.get_or_create(
                product=product,
                client=client,
                price=product.price,
            )
            if created:
                created_clients.append(client.name)
            else:
                existing_clients.append(client.name)

    summary: Dict[str, object] = {
        "created_count": len(created_clients),
        "existing_count": len(existing_clients),
        "created_clients": created_clients,
        "existing_clients": existing_clients,
    }

    logger.info(
        "Ensured product for all clients", extra={
            "product_id": product.id,
            "product_name": product.name,
            "created_count": summary["created_count"],
            "existing_count": summary["existing_count"],
            "user": getattr(user, 'username', None),
        }
    )

    return summary


def bulk_increase_product_client_prices(
    *,
    product: Product,
    amount: Optional[float] = None,
    percent: Optional[float] = None,
    note: str = '',
    user=None,
) -> Dict[str, object]:
    """Increase active client prices for a single product.

    Args:
        product: Product to update (must be active).
        amount: Fixed increment to add to each price.
        percent: Percentage increment to apply to each price (e.g., 10 for 10%).
        note: Optional note to append to the price record.
        user: Requesting user for logging (optional).

    Returns:
        Dict with updated_count and mode.
    """

    if product is None:
        raise ValueError('Debe seleccionar un producto antes de actualizar precios.')
    if not product.active:
        raise ValueError('El producto debe estar activo para actualizar precios.')
    if (amount is None and percent is None) or (amount is not None and percent is not None):
        raise ValueError('Proporcione solo un tipo de incremento: monto fijo o porcentaje.')

    qs = ProductClientPrice.objects.select_for_update().filter(
        product=product,
        active=True,
        client__active=True,
    )

    updated = 0
    mode = 'amount' if amount is not None else 'percent'

    with transaction.atomic():
        for price_row in qs:
            delta = amount if amount is not None else price_row.price * (percent / 100)
            new_price = price_row.price + delta
            price_row.price = new_price
            if note:
                price_row.note = f"{note}" if not price_row.note else f"{price_row.note} | {note}"
            price_row.save(update_fields=['price', 'note'])
            updated += 1
        product.price = new_price  # Update product's base price if needed
        product.save()

    logger.info(
        'Bulk increased product client prices',
        extra={
            'product_id': product.id,
            'product_name': product.name,
            'mode': mode,
            'amount': amount,
            'percent': percent,
            'updated_count': updated,
            'user': getattr(user, 'username', None),
        },
    )

    return {'updated_count': updated, 'mode': mode, 'amount': amount, 'percent': percent}
