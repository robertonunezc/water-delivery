from django.urls import reverse
from django.contrib.auth import get_user_model
from decimal import Decimal
from unittest.mock import patch, MagicMock
import json
from tenant_client.test_utils import FastTenantTestCase

from clients.models import Address, Client, InvoiceData

User = get_user_model()
from orders.models import Order, OrderProduct, OrderStatus
from orders import services
from payment.models import Payment
from product.models import Product, ProductClientPrice, ProductCategory
from invoice.models import Invoice


class UpdateOrderTestCase(FastTenantTestCase):
    """Tests for the update_order service function."""

    def setUp(self) -> None:
        self.client = Client.objects.create(
            name="Test Client",
            balance=Decimal("100.00"),
            credit_limit=Decimal("500.00"),
        )
        self.category = ProductCategory.objects.create(name="Water")
        self.product = Product.objects.create(
            name="Garrafon",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
        )
        self.order = Order.objects.create(
            client=self.client,
            total_amount=Decimal("0.00"),
        )

    def test_update_order_creates_order_product_with_client_price(self) -> None:
        """Test that update_order creates an OrderProduct with client-specific price."""
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=25.00,
        )

        result = services.update_order(
            order=self.order,
            quantity=3,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("75.00"))
        order_product = OrderProduct.objects.get(order=self.order, product=self.product)
        self.assertEqual(order_product.quantity, 3)
        self.assertEqual(order_product.unit_price, Decimal("25.00"))

    def test_update_order_uses_base_price_when_no_client_price(self) -> None:
        """Test that update_order uses base_price when no client-specific price exists."""
        self.product.base_price = 30.00
        self.product.save()

        result = services.update_order(
            order=self.order,
            quantity=2,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("60.00"))
        order_product = OrderProduct.objects.get(order=self.order, product=self.product)
        self.assertEqual(order_product.unit_price, Decimal("30.00"))

    def test_update_order_updates_existing_order_product(self) -> None:
        """Test that update_order updates quantity when OrderProduct already exists."""
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=20.00,
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            unit_price=Decimal("20.00"),
        )

        result = services.update_order(
            order=self.order,
            quantity=5,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("100.00"))
        order_product = OrderProduct.objects.get(order=self.order, product=self.product)
        self.assertEqual(order_product.quantity, 5)

    def test_update_order_deletes_product_when_quantity_zero(self) -> None:
        """Test that update_order removes OrderProduct when quantity is 0."""
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=20.00,
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=3,
            unit_price=Decimal("20.00"),
        )
        self.order.total_amount = Decimal("60.00")
        self.order.save()

        result = services.update_order(
            order=self.order,
            quantity=0,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("0.00"))
        self.assertFalse(
            OrderProduct.objects.filter(order=self.order, product=self.product).exists()
        )

    def test_update_order_deletes_product_when_quantity_negative(self) -> None:
        """Test that update_order removes OrderProduct when quantity is negative."""
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=20.00,
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=Decimal("20.00"),
        )

        result = services.update_order(
            order=self.order,
            quantity=-1,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("0.00"))
        self.assertFalse(
            OrderProduct.objects.filter(order=self.order, product=self.product).exists()
        )

    def test_update_order_with_multiple_products(self) -> None:
        """Test that update_order correctly calculates total with multiple products."""
        product2 = Product.objects.create(
            name="Botella",
            presentation="1",
            unit_of_measure=1,
            category=self.category,
        )
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=25.00,
        )
        ProductClientPrice.objects.create(
            product=product2,
            client=self.client,
            price=10.00,
        )

        services.update_order(
            order=self.order,
            quantity=2,
            product=self.product,
            client=self.client,
        )
        result = services.update_order(
            order=self.order,
            quantity=3,
            product=product2,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("80.00"))

    def test_update_order_with_discount(self) -> None:
        """Test that update_order applies discount correctly."""
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=25.00,
        )

        result = services.update_order(
            order=self.order,
            quantity=4,
            product=self.product,
            client=self.client,
            discount=Decimal("10.00"),
        )

        self.assertEqual(result.total_amount, Decimal("90.00"))


class UpdateOrderViewTestCase(FastTenantTestCase):
    """Integration tests for update_order endpoint behavior."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="order_user", password="testpass")
        self.client.force_login(self.user)

        self.customer = Client.objects.create(
            name="Client Endpoint",
            balance=Decimal("200.00"),
            credit_limit=Decimal("500.00"),
        )
        self.category = ProductCategory.objects.create(name="Water")
        self.product_1 = Product.objects.create(
            name="Garrafon",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
            price=20.0,
        )
        self.product_2 = Product.objects.create(
            name="Botella",
            presentation="1",
            unit_of_measure=1,
            category=self.category,
            price=10.0,
        )

        ProductClientPrice.objects.create(
            product=self.product_1,
            client=self.customer,
            price=20.0,
        )
        ProductClientPrice.objects.create(
            product=self.product_2,
            client=self.customer,
            price=10.0,
        )

        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.PENDING.value,
            discount=Decimal("0.00"),
            subtotal_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product_1,
            quantity=2,
            unit_price=Decimal("20.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product_2,
            quantity=1,
            unit_price=Decimal("10.00"),
        )
        self.order.total_amount = services.calculate_order_total(self.order)
        self.order.save(update_fields=['subtotal_amount', 'total_amount'])

    def _post_update(self, payload: dict):
        return self.client.post(
            reverse('orders:update_order', kwargs={'order_pk': self.order.pk}),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_update_endpoint_removes_product_and_recalculates_totals(self) -> None:
        response = self._post_update(
            {
                "quantity": 0,
                "product_id": str(self.product_1.pk),
                "discount": 0,
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertFalse(
            OrderProduct.objects.filter(order=self.order, product=self.product_1).exists()
        )
        self.assertEqual(self.order.subtotal_amount, Decimal("10.00"))
        self.assertEqual(self.order.total_amount, Decimal("10.00"))

    def test_update_endpoint_changes_quantity_and_discount(self) -> None:
        response = self._post_update(
            {
                "quantity": 3,
                "product_id": str(self.product_2.pk),
                "discount": "5.00",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        item = OrderProduct.objects.get(order=self.order, product=self.product_2)
        self.assertEqual(item.quantity, 3)
        self.assertEqual(self.order.subtotal_amount, Decimal("70.00"))
        self.assertEqual(self.order.total_amount, Decimal("65.00"))

    def test_update_endpoint_discount_only_recalculates_total(self) -> None:
        response = self._post_update(
            {
                "quantity": 0,
                "discount": "12.00",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.discount, Decimal("12.00"))
        self.assertEqual(self.order.subtotal_amount, Decimal("50.00"))
        self.assertEqual(self.order.total_amount, Decimal("38.00"))

    def test_update_endpoint_notes_only_keeps_existing_totals(self) -> None:
        response = self._post_update(
            {
                "notes": "Entregar antes de las 5 pm",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.notes, "Entregar antes de las 5 pm")
        self.assertEqual(self.order.discount, Decimal("0.00"))
        self.assertEqual(self.order.subtotal_amount, Decimal("50.00"))
        self.assertEqual(self.order.total_amount, Decimal("50.00"))

    def test_update_endpoint_product_change_can_persist_notes(self) -> None:
        response = self._post_update(
            {
                "quantity": 3,
                "product_id": str(self.product_1.pk),
                "discount": "0.00",
                "notes": "Cliente solicita tocar el timbre",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.notes, "Cliente solicita tocar el timbre")
        self.assertEqual(self.order.subtotal_amount, Decimal("70.00"))
        self.assertEqual(self.order.total_amount, Decimal("70.00"))


class CancelOrderServiceTestCase(FastTenantTestCase):
    """Tests for cancel_pending_order service function."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="cancel_service_user", password="testpass")
        self.customer = Client.objects.create(name="Cliente Cancelación Servicio")
        self.category = ProductCategory.objects.create(name="Water Service")
        self.product = Product.objects.create(
            name="Garrafón Servicio",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
        )
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.PENDING.value,
            total_amount=Decimal("50.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=Decimal("25.00"),
        )

    def test_cancel_pending_order_deletes_order_and_items(self) -> None:
        result = services.cancel_pending_order(order=self.order, user=self.user)

        self.assertTrue(result["success"])
        self.assertFalse(Order.objects.filter(pk=self.order.pk).exists())
        self.assertFalse(OrderProduct.objects.filter(order_id=self.order.pk).exists())

    def test_cancel_pending_order_rejects_non_pending_status(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.save(update_fields=['status'])

        result = services.cancel_pending_order(order=self.order, user=self.user)

        self.assertFalse(result["success"])
        self.assertIn("pendiente", result["error"])
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())

    def test_cancel_pending_order_rejects_order_with_payments(self) -> None:
        Payment.objects.create(
            amount=Decimal("50.00"),
            method='cash',
            client=self.customer,
            order=self.order,
            status='pending',
            created_by=self.user,
        )

        result = services.cancel_pending_order(order=self.order, user=self.user)

        self.assertFalse(result["success"])
        self.assertIn("pagos", result["error"])
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())


class CancelOrderViewTestCase(FastTenantTestCase):
    """Integration tests for cancel_order endpoint behavior."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="cancel_view_user", password="testpass")
        self.client.force_login(self.user)
        self.customer = Client.objects.create(name="Cliente Cancelación Vista")
        self.category = ProductCategory.objects.create(name="Water View")
        self.product = Product.objects.create(
            name="Garrafón Vista",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
        )
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.PENDING.value,
            total_amount=Decimal("50.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=Decimal("25.00"),
        )

    def test_cancel_order_endpoint_deletes_order(self) -> None:
        response = self.client.post(
            reverse('orders:cancel_order', kwargs={'order_pk': self.order.pk}),
            data=json.dumps({}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get('success'))
        self.assertIn('redirect_url', payload)
        self.assertFalse(Order.objects.filter(pk=self.order.pk).exists())

    def test_cancel_order_endpoint_returns_400_for_non_pending(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.save(update_fields=['status'])

        response = self.client.post(
            reverse('orders:cancel_order', kwargs={'order_pk': self.order.pk}),
            data=json.dumps({}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload.get('success'))
        self.assertIn('error', payload)


class OrdersDashboardBulkActionTestCase(FastTenantTestCase):
    """Tests for the dashboard bulk actions UI endpoint."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="dashboard_user",
            password="testpass",
            is_staff=True,
        )
        self.client.force_login(self.user)

        self.customer = Client.objects.create(name="Bulk Client", type="corporate")
        self.other_customer = Client.objects.create(name="Other Bulk Client", type="corporate")
        self._make_invoice_ready(self.customer)
        self._make_invoice_ready(self.other_customer)

        self.completed_order_1 = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("50.00"),
        )
        self.completed_order_2 = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("30.00"),
        )
        self.pending_order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.PENDING.value,
            total_amount=Decimal("20.00"),
        )
        self.other_client_order = Order.objects.create(
            client=self.other_customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("40.00"),
        )

    def _make_invoice_ready(self, client: Client) -> None:
        rfc_prefix = (client.name.upper().replace(' ', '') + 'XXXX')[:4]
        InvoiceData.objects.create(
            client=client,
            rfc=f'{rfc_prefix}010101AAA',
            razon_social=f'{client.name} SA de CV',
        )
        Address.objects.create(
            client=client,
            type='billing',
            street='Fiscal 123',
            locality='Centro',
            municipality='Queretaro',
            state='Queretaro',
            zip_code='76000',
            country='Mexico',
        )

    def test_dashboard_bulk_create_invoice_creates_invoice(self) -> None:
        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'create_invoice',
                'selected_orders': [self.completed_order_1.pk, self.completed_order_2.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(client=self.customer)
        self.assertEqual(invoice.amount, Decimal('80.00'))
        self.assertEqual(invoice.invoice_links.count(), 2)
        linked_order_ids = set(invoice.invoice_links.values_list('order_id', flat=True))
        self.assertSetEqual(
            linked_order_ids,
            {self.completed_order_1.id, self.completed_order_2.id},
        )

    def test_dashboard_bulk_create_invoice_rejects_non_completed_orders(self) -> None:
        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'create_invoice',
                'selected_orders': [self.completed_order_1.pk, self.pending_order.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.exists())
        self.assertContains(response, 'Solo se pueden facturar pedidos completados')

    def test_dashboard_bulk_create_invoice_rejects_client_without_invoice_data(self) -> None:
        InvoiceData.objects.filter(client=self.customer).delete()

        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'create_invoice',
                'selected_orders': [self.completed_order_1.pk, self.completed_order_2.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.exists())
        self.assertContains(response, 'no puede facturarse')
        self.assertContains(response, 'RFC')

    def test_dashboard_bulk_create_invoice_rejects_branch_when_corporate_lacks_billing_address(self) -> None:
        corporate = Client.objects.create(name='Corporate Client', type='corporate')
        self._make_invoice_ready(corporate)
        corporate.addresses.filter(type='billing').delete()

        branch = Client.objects.create(
            name='Branch Client',
            type='branch',
            corporate=corporate,
            billing_override_enabled=False,
        )
        order = Order.objects.create(
            client=branch,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('60.00'),
        )

        response = self.client.post(
            reverse('admin_orders'),
            data={'bulk_action': 'create_invoice', 'selected_orders': [order.pk]},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(client=branch).exists())
        self.assertContains(response, 'cliente corporativo')
        self.assertContains(response, 'domicilio de tipo fiscal activo')

    def test_dashboard_bulk_create_invoice_rejects_branch_override_without_own_billing_data(self) -> None:
        corporate = Client.objects.create(name='Corporate Override', type='corporate')
        self._make_invoice_ready(corporate)

        branch = Client.objects.create(
            name='Branch Override',
            type='branch',
            corporate=corporate,
            billing_override_enabled=True,
        )
        order = Order.objects.create(
            client=branch,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('45.00'),
        )

        response = self.client.post(
            reverse('admin_orders'),
            data={'bulk_action': 'create_invoice', 'selected_orders': [order.pk]},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(client=branch).exists())
        self.assertContains(response, 'el mismo cliente')
        self.assertContains(response, 'RFC')

    def test_dashboard_bulk_status_update_uses_service_layer(self) -> None:
        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'mark_pending',
                'selected_orders': [self.completed_order_1.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.completed_order_1.refresh_from_db()
        self.assertEqual(self.completed_order_1.status, OrderStatus.PENDING.value)

class CalculateOrderTotalTestCase(FastTenantTestCase):
    """Tests for the calculate_order_total service function."""

    def setUp(self) -> None:
        self.client = Client.objects.create(name="Test Client")
        self.category = ProductCategory.objects.create(name="Water")
        self.product1 = Product.objects.create(
            name="Garrafon",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
        )
        self.product2 = Product.objects.create(
            name="Botella",
            presentation="1",
            unit_of_measure=1,
            category=self.category,
        )
        self.order = Order.objects.create(
            client=self.client,
            total_amount=Decimal("0.00"),
        )

    def test_calculate_order_total_empty_order(self) -> None:
        """Test that calculate_order_total returns 0 for empty order."""
        total = services.calculate_order_total(self.order)
        self.assertEqual(total, Decimal("0.00"))

    def test_calculate_order_total_single_item(self) -> None:
        """Test calculate_order_total with a single item."""
        OrderProduct.objects.create(
            order=self.order,
            product=self.product1,
            quantity=3,
            unit_price=Decimal("25.00"),
        )

        total = services.calculate_order_total(self.order)
        self.assertEqual(total, Decimal("75.00"))

    def test_calculate_order_total_multiple_items(self) -> None:
        """Test calculate_order_total with multiple items."""
        OrderProduct.objects.create(
            order=self.order,
            product=self.product1,
            quantity=2,
            unit_price=Decimal("25.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product2,
            quantity=5,
            unit_price=Decimal("10.00"),
        )

        total = services.calculate_order_total(self.order)
        self.assertEqual(total, Decimal("100.00"))

    def test_calculate_order_total_with_decimal_prices(self) -> None:
        """Test calculate_order_total handles decimal prices correctly."""
        OrderProduct.objects.create(
            order=self.order,
            product=self.product1,
            quantity=3,
            unit_price=Decimal("15.50"),
        )

        total = services.calculate_order_total(self.order)
        self.assertEqual(total, Decimal("46.50"))


class ProcessOrderPaymentTestCase(FastTenantTestCase):
    """Tests for the process_order_payment service function."""

    def setUp(self) -> None:
        self.client = Client.objects.create(
            name="Test Client",
            balance=Decimal("100.00"),
            credit_limit=Decimal("500.00"),
            current_debt=Decimal("0.00"),
            can_pay_with_credit=True,
        )
        self.order = Order.objects.create(
            client=self.client,
            total_amount=Decimal("50.00"),
        )

    @patch("clients.services.balance_service.deduct_balance")
    def test_process_order_payment_balance_only_success(
        self, mock_deduct_balance: MagicMock
    ) -> None:
        """Test payment using balance only when sufficient balance exists."""
        mock_deduct_balance.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="balance",
            order=self.order,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["balance_used"], Decimal("50.00"))
        self.assertEqual(result["credit_used"], Decimal("0"))
        mock_deduct_balance.assert_called_once()

    def test_process_order_payment_balance_only_insufficient(self) -> None:
        """Test payment fails when balance is insufficient and method is balance."""
        self.client.balance = Decimal("30.00")
        self.client.save()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="balance",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertIn("Insufficient balance", result["error"])
        self.assertEqual(result["balance_used"], Decimal("0"))

    @patch("clients.services.balance_service.add_debt")
    def test_process_order_payment_credit_only_success(
        self, mock_add_debt: MagicMock
    ) -> None:
        """Test payment using credit only when sufficient credit exists."""
        mock_add_debt.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["credit_used"], Decimal("50.00"))
        self.assertEqual(result["balance_used"], Decimal("0"))
        mock_add_debt.assert_called_once()

    def test_process_order_payment_credit_only_insufficient(self) -> None:
        """Test payment fails when credit is insufficient and method is credit."""
        self.client.current_debt = Decimal("480.00")
        self.client.save()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertIn("Insufficient credit", result["error"])

    def test_process_order_payment_credit_disabled(self) -> None:
        """Test payment fails when client cannot use credit and has no available credit."""
        self.client.can_pay_with_credit = False
        self.client.balance = Decimal("0.00")
        self.client.credit_limit = Decimal("0.00")
        self.client.save()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertIn("not allowed to pay with credit", result["error"])

    def test_process_order_payment_credit_succeeds_without_note(self) -> None:
        """Test credit payments no longer require a note."""
        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
            credit_note=None,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["credit_used"], Decimal("50.00"))

    @patch("clients.services.balance_service.add_debt")
    def test_process_order_payment_credit_with_note(
        self, mock_add_debt: MagicMock
    ) -> None:
        """Test payment succeeds and preserves optional credit notes."""
        mock_add_debt.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
            credit_note="Authorized by manager",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["credit_used"], Decimal("50.00"))

    @patch("clients.services.balance_service.deduct_balance")
    def test_process_order_payment_auto_uses_balance_first(
        self, mock_deduct_balance: MagicMock
    ) -> None:
        """Test auto method uses balance first before credit."""
        mock_deduct_balance.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="auto",
            order=self.order,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["balance_used"], Decimal("50.00"))
        self.assertEqual(result["credit_used"], Decimal("0"))
        mock_deduct_balance.assert_called_once()

    @patch("clients.services.balance_service.add_debt")
    @patch("clients.services.balance_service.deduct_balance")
    def test_process_order_payment_auto_mixed_balance_and_credit(
        self, mock_deduct_balance: MagicMock, mock_add_debt: MagicMock
    ) -> None:
        """Test auto method uses balance first then credit for remainder."""
        self.client.balance = Decimal("30.00")
        self.client.save()
        mock_deduct_balance.return_value = MagicMock()
        mock_add_debt.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="auto",
            order=self.order,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["balance_used"], Decimal("30.00"))
        self.assertEqual(result["credit_used"], Decimal("20.00"))

    def test_process_order_payment_auto_insufficient_total_funds(self) -> None:
        """Test auto method fails when total funds are insufficient."""
        self.client.balance = Decimal("30.00")
        self.client.current_debt = Decimal("490.00")
        self.client.save()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="auto",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertIn("Insufficient funds", result["error"])

    def test_process_order_payment_auto_cannot_use_credit_insufficient_balance(
        self,
    ) -> None:
        """Test auto fails when credit disabled, no available credit, and balance insufficient."""
        self.client.balance = Decimal("30.00")
        self.client.can_pay_with_credit = False
        self.client.credit_limit = Decimal("0.00")
        self.client.save()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="auto",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertIn("cannot use credit", result["error"])


class OrderPaymentRoutingTestCase(FastTenantTestCase):
    """Tests for the active order payment route."""

    def test_pay_order_url_resolves_to_view_not_legacy_service(self) -> None:
        from django.urls import resolve, reverse
        from orders import views

        match = resolve(reverse("orders:create_payment_for_order", args=[1]))

        self.assertIs(match.func, views.create_payment_for_order)
        self.assertFalse(hasattr(services, "create_payment_for_order"))
