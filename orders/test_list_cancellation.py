import json
from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.urls import reverse

from clients.models import Client
from invoice.models import Invoice, InvoiceOrderLink
from orders.models import Order, OrderStatus
from tenant_client.test_utils import FastTenantTestCase


class CancellationFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.actions: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == 'form' and attributes.get('method') == 'post':
            self.actions.append(attributes.get('action', ''))


class OrderListCancellationTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username='cancellation-admin', password='test',
        )
        self.client.force_login(self.user)
        customer = Client.objects.create(name='Cliente cancelación', type='corporate')
        self.order = Order.objects.create(client=customer, owner=self.user, total_amount=0)

    def test_lists_offer_cancellation_only_for_active_orders(self) -> None:
        completed = Order.objects.create(
            client=self.order.client, owner=self.user, total_amount=0,
            status=OrderStatus.COMPLETED.value,
        )
        cancelled = Order.objects.create(
            client=self.order.client, owner=self.user, total_amount=0,
            status=OrderStatus.CANCELLED.value,
        )
        for url_name in ('orders:list', 'admin_orders', 'report:orders_report'):
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                parser = CancellationFormParser()
                parser.feed(response.content.decode())
                for order in (self.order, completed):
                    self.assertIn(reverse('orders:cancel_order', args=[order.pk]), parser.actions)
                self.assertNotIn(reverse('orders:cancel_order', args=[cancelled.pk]), parser.actions)

    def test_form_cancellation_returns_to_filtered_list(self) -> None:
        next_url = f"{reverse('admin_orders')}?status=PENDING&page=2"
        response = self.client.post(
            reverse('orders:cancel_order', args=[self.order.pk]),
            {'response_format': 'html', 'next': next_url},
        )

        self.assertRedirects(response, next_url, fetch_redirect_response=False)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)

    def test_form_cancellation_does_not_redirect_to_another_host(self) -> None:
        response = self.client.post(
            reverse('orders:cancel_order', args=[self.order.pk]),
            {'response_format': 'html', 'next': 'https://example.org/'},
        )

        self.assertRedirects(response, reverse('orders:list'), fetch_redirect_response=False)

    def test_json_cancellation_keeps_existing_response_contract(self) -> None:
        response = self.client.post(
            reverse('orders:cancel_order', args=[self.order.pk]),
            json.dumps({}), content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)

    def test_blocked_form_cancellation_shows_reason_and_preserves_order(self) -> None:
        invoice = Invoice.objects.create(
            client=self.order.client, amount=0, identifier='A', folio='1',
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=self.order)
        next_url = reverse('admin_orders')

        response = self.client.post(
            reverse('orders:cancel_order', args=[self.order.pk]),
            {'response_format': 'html', 'next': next_url}, follow=True,
        )

        self.assertRedirects(response, next_url)
        self.assertContains(response, 'El pedido ya está vinculado a una factura')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING.value)
        self.assertTrue(self.order.cancellation_review_required)

    def test_get_does_not_cancel_order(self) -> None:
        response = self.client.get(reverse('orders:cancel_order', args=[self.order.pk]))

        self.assertEqual(response.status_code, 405)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING.value)
