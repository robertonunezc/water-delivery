import logging
from typing import Any

from django.db import transaction

from clients.models import Client
from product.models import Product, ProductClientPrice
from product.services import create_or_restore_product_client_price

logger = logging.getLogger(__name__)


def build_client_product_price_initial(client: Client) -> list[dict[str, object]]:
    products = Product.objects.all().order_by('name', 'presentation', 'unit_of_measure')
    prices_by_product_id = {
        price_row.product_id: price_row
        for price_row in ProductClientPrice.objects.filter(
            client=client,
            product__in=products,
        )
    }

    initial_rows: list[dict[str, object]] = []
    for product in products:
        price_row = prices_by_product_id.get(product.pk)
        initial_rows.append({
            'product_id': product.pk,
            'price': price_row.price if price_row else product.price,
            'active': price_row.active if price_row else True,
            'note': price_row.note if price_row else '',
        })

    return initial_rows


def update_client_product_prices(
    *,
    client: Client,
    forms: list[Any],
    user: Any = None,
) -> dict[str, int]:
    created_count = 0
    updated_count = 0

    with transaction.atomic():
        for form in forms:
            product = form.product
            price = form.cleaned_data['price']
            _, created = create_or_restore_product_client_price(
                product=product,
                client=client,
                price=float(price),
                active=form.cleaned_data.get('active', False),
                note=form.cleaned_data.get('note', ''),
                update_existing=True,
                validate=True,
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

    logger.info(
        'Updated client product prices',
        extra={
            'client_id': client.pk,
            'client_name': client.name,
            'created_count': created_count,
            'updated_count': updated_count,
            'user': getattr(user, 'username', None),
        },
    )

    return {'created_count': created_count, 'updated_count': updated_count}
