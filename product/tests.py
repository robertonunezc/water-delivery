from django.contrib.auth import get_user_model
from django.urls import reverse

from tenant_client.test_utils import FastTenantTestCase

from clients.models import Client

from .csv_import_service import import_products_and_prices_from_csv
from .models import Product, ProductClientPrice
from .services import ensure_client_product_prices, ensure_product_for_all_clients

User = get_user_model()


class ProductAdminPriceTabTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='product_admin',
            password='testpass123',
            is_staff=True,
        )
        self.client.force_login(self.user)
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

    def test_price_tab_renders_client_price_search_input(self) -> None:
        response = self.client.get(
            f"{reverse('admin_edit_product', kwargs={'pk': self.product.pk})}?tab=prices"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="product-client-price-search"')
        self.assertContains(response, 'data-price-search-row')

    def test_price_tab_delete_label_targets_delete_checkbox(self) -> None:
        response = self.client.get(
            f"{reverse('admin_edit_product', kwargs={'pk': self.product.pk})}?tab=prices"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<label class="pg-checkbox-label" for="id_prices-0-DELETE">Eliminar</label>',
            html=True,
        )

    def test_price_tab_delete_post_soft_deletes_client_price(self) -> None:
        response = self.client.post(
            reverse('admin_edit_product', kwargs={'pk': self.product.pk}),
            data={
                'section': 'prices',
                'prices-TOTAL_FORMS': '1',
                'prices-INITIAL_FORMS': '1',
                'prices-MIN_NUM_FORMS': '0',
                'prices-MAX_NUM_FORMS': '1000',
                'prices-0-id': str(self.client_price.pk),
                'prices-0-client': str(self.client_record.pk),
                'prices-0-price': '25.00',
                'prices-0-active': 'on',
                'prices-0-note': '',
                'prices-0-DELETE': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.client_price.refresh_from_db()
        self.assertIsNotNone(self.client_price.deleted_at)
        self.assertFalse(ProductClientPrice.objects.filter(pk=self.client_price.pk).exists())

    def test_price_tab_create_restores_soft_deleted_client_price(self) -> None:
        self.client_price.delete()
        self.client.raise_request_exception = False

        response = self.client.post(
            reverse('admin_edit_product', kwargs={'pk': self.product.pk}),
            data={
                'section': 'prices',
                'prices-TOTAL_FORMS': '1',
                'prices-INITIAL_FORMS': '0',
                'prices-MIN_NUM_FORMS': '0',
                'prices-MAX_NUM_FORMS': '1000',
                'prices-0-id': '',
                'prices-0-client': str(self.client_record.pk),
                'prices-0-price': '30.00',
                'prices-0-active': 'on',
                'prices-0-note': 'restaurado',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.client_price.refresh_from_db()
        self.assertIsNone(self.client_price.deleted_at)
        self.assertEqual(self.client_price.price, 30.0)
        self.assertEqual(self.client_price.note, 'restaurado')
        self.assertEqual(
            ProductClientPrice.all_objects.filter(
                product=self.product,
                client=self.client_record,
            ).count(),
            1,
        )

    def test_price_tab_create_rejects_duplicate_client_price(self) -> None:
        response = self.client.post(
            reverse('admin_edit_product', kwargs={'pk': self.product.pk}),
            data={
                'section': 'prices',
                'prices-TOTAL_FORMS': '2',
                'prices-INITIAL_FORMS': '1',
                'prices-MIN_NUM_FORMS': '0',
                'prices-MAX_NUM_FORMS': '1000',
                'prices-0-id': str(self.client_price.pk),
                'prices-0-client': str(self.client_record.pk),
                'prices-0-price': '25.00',
                'prices-0-active': 'on',
                'prices-0-note': '',
                'prices-1-id': '',
                'prices-1-client': str(self.client_record.pk),
                'prices-1-price': '30.00',
                'prices-1-active': 'on',
                'prices-1-note': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'No se puede asignar el mismo cliente más de una vez para este producto.',
        )
        self.assertEqual(
            ProductClientPrice.all_objects.filter(
                product=self.product,
                client=self.client_record,
            ).count(),
            1,
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

    def test_csv_import_restores_soft_deleted_client_price(self) -> None:
        self.client_price.delete()
        csv_body = (
            "product_name,presentation,unit_of_measure,base_price,category,client_name,client_price\n"
            f"{self.product.name},{self.product.presentation},lt,25.00,,{self.client_record.name},31.50\n"
        )

        summary = import_products_and_prices_from_csv(csv_body.encode('utf-8'))

        self.assertEqual(summary.errors, [])
        self.assertEqual(summary.created_client_prices, 1)
        self.assertEqual(summary.updated_client_prices, 0)
        self.client_price.refresh_from_db()
        self.assertIsNone(self.client_price.deleted_at)
        self.assertEqual(self.client_price.price, 31.5)
        self.assertEqual(
            ProductClientPrice.all_objects.filter(
                product=self.product,
                client=self.client_record,
            ).count(),
            1,
        )
