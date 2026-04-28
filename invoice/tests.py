from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from clients.models import Client
from orders.models import Order
from invoice.models import Invoice, InvoiceOrderLink
from invoice.admin import InvoiceOrderLinkAdminForm


class BillingOrderAdminFormTests(TestCase):
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

	def test_validation_fails_when_sum_exceeds_billing_amount(self):
		br = Invoice.objects.create(
			client=self.client_a,
			amount=Decimal('100.00'),
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
			data={
				'invoice': br.id,
				'order': new_order.id,
				'is_paid': False,
				'partially_paid': False,
				'amount_paid': '0',
				'payment_date': '',
			}
		)

		self.assertFalse(form.is_valid())
		self.assertIn('order', form.errors)

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
