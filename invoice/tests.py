from decimal import Decimal
from datetime import timedelta
import json

from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory
from django.utils import timezone

from clients.models import Address, Client, InvoiceData
from orders.models import Order
from invoice.models import Invoice, InvoiceOrderLink
from invoice.admin import InvoiceOrderLinkAdminForm, InvoiceOrderLinkAdmin
from invoice.services import validate_invoice_order_total
from invoice.views import invoiceable_orders, invoice_client
from tenant_client.test_utils import FastTenantTestCase
from django.urls import reverse


class InvoiceTenantTestCase(FastTenantTestCase):
	@classmethod
	def setup_tenant(cls, tenant):
		tenant.name = 'Test Tenant'
		tenant.paid_until = timezone.now().date() + timedelta(days=30)
		tenant.on_trial = False
		return tenant


class BillingOrderAdminFormTests(InvoiceTenantTestCase):
		def setUp(self):
			self.client_a = Client.objects.create(name="Client A")
			self.client_b = Client.objects.create(name="Client B")

		def _set_datetime(self, obj, field_name, dt):
			type(obj).objects.filter(pk=obj.pk).update(**{field_name: dt})
			# refresh from db to reflect changes
			obj.refresh_from_db()

		def test_order_queryset_filters_by_client_status_and_unbilled(self):
			base_time = timezone.now()

			# Invoice for client A
			br = Invoice.objects.create(
				client=self.client_a,
				amount=Decimal('100.00'),
				identifier='SER-001',
				folio='FOL-001',
				emmited_at=base_time,
			)

			# Orders
			order_a_before_unbilled = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('10.00'),
				status='COMPLETED',
			)
			self._set_datetime(order_a_before_unbilled, 'order_date', base_time - timedelta(days=1))

			order_a_after_unbilled = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('20.00'),
				status='COMPLETED',
			)
			self._set_datetime(order_a_after_unbilled, 'order_date', base_time + timedelta(hours=1))

			order_b_after_unbilled = Order.objects.create(
				client=self.client_b,
				total_amount=Decimal('30.00'),
				status='COMPLETED',
			)
			self._set_datetime(order_b_after_unbilled, 'order_date', base_time + timedelta(hours=2))

			order_a_before_pending = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('15.00'),
				status='PENDING',
			)
			self._set_datetime(order_a_before_pending, 'order_date', base_time - timedelta(hours=3))

			# An order already linked to ANY invoice should be excluded
			other_br = Invoice.objects.create(
				client=self.client_a,
				amount=Decimal('500.00'),
				identifier='SER-002',
				folio='FOL-002',
				emmited_at=base_time,
			)
			order_a_linked_elsewhere = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('40.00'),
				status='COMPLETED',
			)
			self._set_datetime(order_a_linked_elsewhere, 'order_date', base_time + timedelta(hours=3))
			InvoiceOrderLink.objects.create(invoice=other_br, order=order_a_linked_elsewhere)

			# Build form as inline with parent invoice
			form = InvoiceOrderLinkAdminForm(invoice=br)
			qs = form.fields['order'].queryset

			self.assertIn(order_a_before_unbilled, qs)
			self.assertIn(order_a_after_unbilled, qs)
			self.assertNotIn(order_b_after_unbilled, qs)
			self.assertNotIn(order_a_before_pending, qs)
			self.assertNotIn(order_a_linked_elsewhere, qs)

		def test_order_queryset_includes_current_order_on_edit(self):
			base_time = timezone.now()

			br = Invoice.objects.create(
				client=self.client_a,
				amount=Decimal('100.00'),
				identifier='SER-003',
				folio='FOL-003',
				emmited_at=base_time,
			)

			current_order = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('50.00'),
				status='PENDING',
			)
			self._set_datetime(current_order, 'order_date', base_time + timedelta(minutes=1))

			bo = InvoiceOrderLink.objects.create(invoice=br, order=current_order)

			# Editing existing instance: form should include the current order even though it's linked
			form = InvoiceOrderLinkAdminForm(instance=bo, invoice=br)
			qs = form.fields['order'].queryset
			self.assertIn(current_order, qs)

		def test_cap_validation_fails_when_sum_exceeds_manual_invoice_amount(self):
			"""Manual invoices (auto_amount=False) enforce sum-of-orders <= amount cap."""
			br = Invoice.objects.create(
				client=self.client_a,
				amount=Decimal('100.00'),
				auto_amount=False,
				identifier='SER-004',
				folio='FOL-004',
				emmited_at=timezone.now(),
			)
			existing_order = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('80.00'),
				status='COMPLETED',
			)
			self._set_datetime(existing_order, 'order_date', timezone.now() - timedelta(days=1))
			InvoiceOrderLink.objects.create(invoice=br, order=existing_order)
			new_order = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('30.00'),
				status='COMPLETED',
			)
			self._set_datetime(new_order, 'order_date', timezone.now() - timedelta(hours=12))
			form = InvoiceOrderLinkAdminForm(
				data={'invoice': br.id, 'order': new_order.id, 'is_paid': False, 'partially_paid': False, 'amount_paid': '0', 'payment_date': ''},
			)
			self.assertFalse(form.is_valid())
			self.assertIn('order', form.errors)

		def test_cap_validation_skipped_for_auto_amount_invoices(self):
			"""Action-created invoices (auto_amount=True) have no cap — amount is derived from orders."""
			br = Invoice.objects.create(
				client=self.client_a,
				amount=Decimal('100.00'),
				auto_amount=True,
				identifier='SER-004B',
				folio='FOL-004B',
				emmited_at=timezone.now(),
			)
			existing_order = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('80.00'),
				status='COMPLETED',
			)
			self._set_datetime(existing_order, 'order_date', timezone.now() - timedelta(days=1))
			InvoiceOrderLink.objects.create(invoice=br, order=existing_order)
			new_order = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('30.00'),
				status='COMPLETED',
			)
			self._set_datetime(new_order, 'order_date', timezone.now() - timedelta(hours=12))
			form = InvoiceOrderLinkAdminForm(
				data={'invoice': br.id, 'order': new_order.id, 'is_paid': False, 'partially_paid': False, 'amount_paid': '0', 'payment_date': ''},
			)
			self.assertTrue(form.is_valid())

		def test_validation_passes_at_boundary_equal_to_billing_amount(self):
			br = Invoice.objects.create(
				client=self.client_a,
				amount=Decimal('100.00'),
				identifier='SER-005',
				folio='FOL-005',
				emmited_at=timezone.now(),
			)

			existing_order = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('80.00'),
				status='COMPLETED',
			)
			self._set_datetime(existing_order, 'order_date', timezone.now() - timedelta(days=1))
			InvoiceOrderLink.objects.create(invoice=br, order=existing_order)

			new_order = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('20.00'),
				status='COMPLETED',
			)
			self._set_datetime(new_order, 'order_date', timezone.now() - timedelta(hours=12))

			form = InvoiceOrderLinkAdminForm(
				data={
					'invoice': br.id,
					'order': new_order.id,
					'is_paid': False,
					'partially_paid': False,
					'amount_paid': '0',
					'payment_date': '',
				}
			)

			self.assertTrue(form.is_valid())

		def test_validation_handles_unsaved_invoice_instance(self):
			unsaved_invoice = Invoice(
				client=self.client_a,
				amount=Decimal('100.00'),
				identifier='SER-006',
				folio='FOL-006',
				emmited_at=timezone.now(),
			)

			new_order = Order.objects.create(
				client=self.client_a,
				total_amount=Decimal('30.00'),
				status='COMPLETED',
			)
			self._set_datetime(new_order, 'order_date', timezone.now() - timedelta(hours=6))

			try:
				validate_invoice_order_total(invoice=unsaved_invoice, order=new_order)
			except ValueError as exc:
				self.fail(f"Unexpected ValueError for unsaved invoice: {exc}")


class InvoiceableOrdersViewTests(InvoiceTenantTestCase):
	"""Tests for the invoiceable_orders and invoice_client views."""

	def setUp(self):
		self.factory = RequestFactory()
		self.user = User.objects.create_user(username='tester', password='pass')
		self.client_a = Client.objects.create(name='Client A')

	def _make_request(self, view_func, url, **kwargs):
		request = self.factory.get(url, **kwargs)
		request.user = self.user
		return request

	def test_invoiceable_orders_returns_completed_unbilled(self):
		order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('50.00'),
			status='COMPLETED',
		)

		request = self._make_request(invoiceable_orders, '/')
		response = invoiceable_orders(request, client_pk=self.client_a.pk)

		self.assertEqual(response.status_code, 200)
		data = json.loads(response.content)
		ids = [o['id'] for o in data['orders']]
		self.assertIn(order.id, ids)

	def test_invoiceable_orders_excludes_already_billed(self):
		invoice = Invoice.objects.create(
			client=self.client_a,
			amount=Decimal('100.00'),
			identifier='S-001',
			folio='F-001',
			emmited_at=timezone.now(),
		)
		billed_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('40.00'),
			status='COMPLETED',
		)
		InvoiceOrderLink.objects.create(invoice=invoice, order=billed_order)

		request = self._make_request(invoiceable_orders, '/')
		response = invoiceable_orders(request, client_pk=self.client_a.pk)

		data = json.loads(response.content)
		ids = [o['id'] for o in data['orders']]
		self.assertNotIn(billed_order.id, ids)

	def test_invoiceable_orders_excludes_pending_orders(self):
		Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('20.00'),
			status='PENDING',
		)

		request = self._make_request(invoiceable_orders, '/')
		response = invoiceable_orders(request, client_pk=self.client_a.pk)

		data = json.loads(response.content)
		self.assertEqual(data['orders'], [])

	def test_invoiceable_orders_includes_linked_order_when_include_order_id_provided(self):
		invoice = Invoice.objects.create(
			client=self.client_a,
			amount=Decimal('100.00'),
			identifier='S-003',
			folio='F-003',
			emmited_at=timezone.now(),
		)
		linked_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('45.00'),
			status='PENDING',
		)
		InvoiceOrderLink.objects.create(invoice=invoice, order=linked_order)

		request = self._make_request(
			invoiceable_orders,
			'/',
			data={'include_order_id': linked_order.id},
		)
		response = invoiceable_orders(request, client_pk=self.client_a.pk)

		data = json.loads(response.content)
		ids = [o['id'] for o in data['orders']]
		self.assertIn(linked_order.id, ids)

	def test_invoice_client_returns_client_info(self):
		invoice = Invoice.objects.create(
			client=self.client_a,
			amount=Decimal('100.00'),
			identifier='S-002',
			folio='F-002',
			emmited_at=timezone.now(),
		)

		request = self._make_request(invoice_client, '/')
		response = invoice_client(request, invoice_id=invoice.pk)

		self.assertEqual(response.status_code, 200)
		data = json.loads(response.content)
		self.assertEqual(data['client_id'], self.client_a.pk)
		self.assertEqual(data['client_name'], self.client_a.name)

	def test_invoice_client_404_for_missing_invoice(self):
		from django.http import Http404
		request = self._make_request(invoice_client, '/')
		with self.assertRaises(Http404):
			invoice_client(request, invoice_id=99999)


class GetInvoiceableOrdersServiceTests(InvoiceTenantTestCase):
	"""Documents the intent: no date-based upper-bound filtering is applied."""

	def setUp(self):
		self.client_a = Client.objects.create(name='Client A')

	def test_orders_after_invoice_date_are_included(self):
		"""
		Intentional behavior: unbilled COMPLETED orders are eligible regardless
		of when they were placed relative to the invoice date. No upper-bound
		date filter is applied.
		"""
		from invoice.services import get_invoiceable_orders_for_client

		future_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('30.00'),
			status='COMPLETED',
		)

		qs = get_invoiceable_orders_for_client(client=self.client_a)
		self.assertIn(future_order, qs)


class CreateInvoiceFromOrdersServiceTests(InvoiceTenantTestCase):
	"""Tests for the create_invoice_from_orders and sync_invoice_amount services."""

	def setUp(self):
		self.client_a = Client.objects.create(name='Client A', type='corporate')
		self.client_b = Client.objects.create(name='Client B', type='corporate')
		self._make_invoice_ready(self.client_a)
		self._make_invoice_ready(self.client_b)

	def _make_invoice_ready(self, client):
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

	def _completed_order(self, client, amount):
		return Order.objects.create(client=client, total_amount=Decimal(str(amount)), status='COMPLETED')

	def test_creates_invoice_with_summed_amount(self):
		from invoice.services import create_invoice_from_orders

		order_a = self._completed_order(self.client_a, '50.00')
		order_b = self._completed_order(self.client_a, '30.00')

		invoice = create_invoice_from_orders(orders=[order_a, order_b], client=self.client_a)

		self.assertEqual(invoice.amount, Decimal('80.00'))
		self.assertEqual(invoice.client, self.client_a)
		self.assertEqual(invoice.invoice_links.count(), 2)
		self.assertTrue(invoice.auto_amount)

	def test_creates_invoice_order_links_for_each_order(self):
		from invoice.services import create_invoice_from_orders

		order_a = self._completed_order(self.client_a, '40.00')
		order_b = self._completed_order(self.client_a, '60.00')

		invoice = create_invoice_from_orders(orders=[order_a, order_b], client=self.client_a)

		linked_order_ids = set(invoice.invoice_links.values_list('order_id', flat=True))
		self.assertIn(order_a.id, linked_order_ids)
		self.assertIn(order_b.id, linked_order_ids)

	def test_raises_if_orders_empty(self):
		from invoice.services import create_invoice_from_orders
		from django.core.exceptions import ValidationError

		with self.assertRaises(ValidationError):
			create_invoice_from_orders(orders=[], client=self.client_a)

	def test_raises_if_orders_from_different_clients(self):
		from invoice.services import create_invoice_from_orders
		from django.core.exceptions import ValidationError

		order_a = self._completed_order(self.client_a, '50.00')
		order_b = self._completed_order(self.client_b, '50.00')

		with self.assertRaises(ValidationError):
			create_invoice_from_orders(orders=[order_a, order_b], client=self.client_a)

	def test_raises_if_client_lacks_required_invoice_data(self):
		from invoice.services import create_invoice_from_orders
		from django.core.exceptions import ValidationError

		invoice_data = self.client_a.invoice_data
		invoice_data.rfc = ''
		invoice_data.razon_social = ''
		invoice_data.save(update_fields=['rfc', 'razon_social', 'updated_at'])
		order_a = self._completed_order(self.client_a, '50.00')
		client = Client.objects.get(pk=self.client_a.pk)

		with self.assertRaisesMessage(ValidationError, 'RFC'):
			create_invoice_from_orders(orders=[order_a], client=client)

	def test_sync_invoice_amount_recalculates_from_linked_orders(self):
		from invoice.services import create_invoice_from_orders, sync_invoice_amount

		order_a = self._completed_order(self.client_a, '50.00')
		invoice = create_invoice_from_orders(orders=[order_a], client=self.client_a)

		# Manually add another order link (simulates user adding via inline)
		order_b = self._completed_order(self.client_a, '25.00')
		InvoiceOrderLink.objects.create(invoice=invoice, order=order_b)

		sync_invoice_amount(invoice)

		self.assertEqual(invoice.amount, Decimal('75.00'))
		invoice.refresh_from_db()
		self.assertEqual(invoice.amount, Decimal('75.00'))

	def test_sync_invoice_amount_with_no_links_sets_zero(self):
		from invoice.services import create_invoice_from_orders, sync_invoice_amount

		order_a = self._completed_order(self.client_a, '50.00')
		invoice = create_invoice_from_orders(orders=[order_a], client=self.client_a)
		invoice.invoice_links.all().delete()

		sync_invoice_amount(invoice)

		self.assertEqual(invoice.amount, Decimal('0'))


class CustomAdminInvoiceViewsTests(InvoiceTenantTestCase):
	def setUp(self):
		super().setUp()
		self.superuser = User.objects.create_superuser(username='admin_staff', password='pass_staff')
		self.client_obj = Client.objects.create(name='Test Client A')
		self.invoice = Invoice.objects.create(
			client=self.client_obj,
			amount=Decimal('200.00'),
			identifier='SER-T1',
			folio='FOL-T1',
			auto_amount=False
		)
		self.client.force_login(self.superuser)

	def test_list_invoices_admin_view(self):
		url = reverse('admin_invoices')
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Test Client A')
		self.assertContains(response, 'SER-T1')

	def test_create_invoice_admin_view_get(self):
		url = reverse('admin_create_invoice')
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)

	def test_create_invoice_admin_view_post(self):
		url = reverse('admin_create_invoice')
		data = {
			'client': self.client_obj.id,
			'identifier': 'SER-NEW',
			'folio': 'FOL-NEW',
			'amount': '150.00',
			'auto_amount': False
		}
		response = self.client.post(url, data)
		self.assertEqual(response.status_code, 302) # Redirect to edit page
		self.assertTrue(Invoice.objects.filter(identifier='SER-NEW').exists())

	def test_edit_invoice_admin_view_get(self):
		url = reverse('admin_edit_invoice', args=[self.invoice.id])
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'SER-T1')

	def test_edit_invoice_admin_view_post_link_order(self):
		# Create completed order
		order = Order.objects.create(
			client=self.client_obj,
			total_amount=Decimal('50.00'),
			status='COMPLETED'
		)

		url = reverse('admin_edit_invoice', args=[self.invoice.id])
		data = {
			'add_order_link': 'true',
			'order': order.id
		}
		response = self.client.post(url, data)
		self.assertEqual(response.status_code, 302) # Redirect to edit page
		self.assertTrue(InvoiceOrderLink.objects.filter(invoice=self.invoice, order=order).exists())


class InvoiceBalanceSnapshotServiceTests(InvoiceTenantTestCase):
	def setUp(self):
		self.client_a = Client.objects.create(name="Balance Snapshot A")
		self.client_b = Client.objects.create(name="Balance Snapshot B")

	def test_invoice_balance_snapshot_separates_capacity_from_unpaid_balance(self):
		from payment.models import Payment
		from invoice.services import get_invoice_balance_snapshot

		invoice = Invoice.objects.create(
			client=self.client_a,
			amount=Decimal("1000.00"),
			identifier="BAL-001",
			folio="BAL-001",
		)
		order_one = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal("400.00"),
			status="COMPLETED",
		)
		order_two = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal("400.00"),
			status="COMPLETED",
		)
		InvoiceOrderLink.objects.create(invoice=invoice, order=order_one)
		InvoiceOrderLink.objects.create(invoice=invoice, order=order_two)
		Payment.objects.create(
			client=self.client_a,
			order=order_one,
			amount=Decimal("600.00"),
			method="cash",
			status="completed",
		)
		Payment.objects.create(
			client=self.client_a,
			order=order_two,
			amount=Decimal("50.00"),
			method="pending_credit",
			status="completed",
		)

		fully_used_invoice = Invoice.objects.create(
			client=self.client_b,
			amount=Decimal("300.00"),
			identifier="BAL-002",
			folio="BAL-002",
		)
		fully_used_order = Order.objects.create(
			client=self.client_b,
			total_amount=Decimal("300.00"),
			status="COMPLETED",
		)
		InvoiceOrderLink.objects.create(invoice=fully_used_invoice, order=fully_used_order)
		Payment.objects.create(
			client=self.client_b,
			order=fully_used_order,
			amount=Decimal("300.00"),
			method="cash",
			status="completed",
		)

		snapshot = get_invoice_balance_snapshot()

		self.assertEqual(snapshot["available_capacity_count"], 1)
		self.assertEqual(snapshot["available_capacity_total"], Decimal("200.00"))
		self.assertEqual(snapshot["unpaid_balance_count"], 1)
		self.assertEqual(snapshot["unpaid_balance_total"], Decimal("400.00"))



# class CrearFacturaActionTests(TestCase):
# 	"""Tests for the crear_factura admin action on OrderAdmin."""

# 	def setUp(self):
# 		self.superuser = User.objects.create_superuser(username='admin', password='pass')
# 		self.client_a = Client.objects.create(name='Client A')
# 		self.client_b = Client.objects.create(name='Client B')
# 		self.test_client = self.__class__._default_client  # avoid name clash with Client model
# 		self.test_client.force_login(self.superuser)

# 	def _completed_order(self, client, amount='50.00'):
# 		return Order.objects.create(client=client, total_amount=Decimal(amount), status='COMPLETED')

# 	def _post_action(self, order_ids):
# 		return self.test_client.post(
# 			'/admin/orders/order/',
# 			{
# 				'action': 'crear_factura',
# 				'_selected_action': order_ids,
# 			},
# 		)

# 	def test_action_creates_invoice_and_redirects_to_change_page(self):
# 		order_a = self._completed_order(self.client_a, '40.00')
# 		order_b = self._completed_order(self.client_a, '60.00')

# 		response = self._post_action([order_a.id, order_b.id])

# 		invoice = Invoice.objects.filter(client=self.client_a).first()
# 		self.assertIsNotNone(invoice)
# 		self.assertEqual(invoice.amount, Decimal('100.00'))
# 		self.assertEqual(invoice.invoice_links.count(), 2)
# 		self.assertRedirects(
# 			response,
# 			f'/admin/billing/invoice/{invoice.id}/change/',
# 			fetch_redirect_response=False,
# 		)

# 	def test_action_rejects_non_completed_orders(self):
# 		order_pending = Order.objects.create(
# 			client=self.client_a, total_amount=Decimal('30.00'), status='PENDING'
# 		)

# 		response = self._post_action([order_pending.id])

# 		self.assertEqual(Invoice.objects.count(), 0)
# 		self.assertEqual(response.status_code, 302)  # redirects back to changelist with error msg

# 	def test_action_rejects_mixed_client_orders(self):
# 		order_a = self._completed_order(self.client_a)
# 		order_b = self._completed_order(self.client_b)

# 		self._post_action([order_a.id, order_b.id])

# 		self.assertEqual(Invoice.objects.count(), 0)

# 	def test_action_rejects_already_billed_orders(self):
# 		order = self._completed_order(self.client_a)
# 		existing_invoice = Invoice.objects.create(
# 			client=self.client_a,
# 			amount=Decimal('50.00'),
# 			identifier='S-EXIST',
# 			folio='F-EXIST',
# 		)
# 		InvoiceOrderLink.objects.create(invoice=existing_invoice, order=order)

# 		self._post_action([order.id])

# 		self.assertEqual(Invoice.objects.count(), 1)  # only the pre-existing one
