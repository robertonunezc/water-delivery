from django.contrib.auth import get_user_model

from tenant_client.test_utils import FastTenantTestCase

from clients.models import Client

from .models import Product, ProductClientPrice
from .services import ensure_client_product_prices, ensure_product_for_all_clients

User = get_user_model()


class ProductPriceServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='product_admin',
            password='testpass123',
            is_staff=True,
        )
        self.product = Product.objects.create(
            name='Garrafón',
            presentation='20',
            unit_of_measure=1,
            price=25.0,
        )
        self.client_record = Client.objects.create(name='Cliente de precio')
        self.client_price = ProductClientPrice.objects.create(
            product=self.product,
            client=self.client_record,
            price=25.0,
        )

    def test_ensure_product_for_all_clients_restores_soft_deleted_client_price(self) -> None:
        self.client_price.delete()

        summary = ensure_product_for_all_clients(self.product, self.user)

        self.client_price.refresh_from_db()
        self.assertIsNone(self.client_price.deleted_at)
        self.assertEqual(self.client_price.price, self.product.price)
        self.assertEqual(summary['created_count'], 1)
        self.assertEqual(
            ProductClientPrice.all_objects.filter(
                product=self.product,
                client=self.client_record,
            ).count(),
            1,
        )

    def test_ensure_client_product_prices_restores_soft_deleted_client_price(self) -> None:
        self.client_price.delete()

        summary = ensure_client_product_prices(self.client_record)

        self.client_price.refresh_from_db()
        self.assertIsNone(self.client_price.deleted_at)
        self.assertEqual(self.client_price.price, self.product.price)
        self.assertEqual(summary['created_count'], 1)
        self.assertEqual(
            ProductClientPrice.all_objects.filter(
                product=self.product,
                client=self.client_record,
            ).count(),
            1,
        )
