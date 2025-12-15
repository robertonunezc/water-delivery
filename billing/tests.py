from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from clients.models import Client
from orders.models import Order
from billing.models import BillingRecord, BillingOrder
from billing.admin import BillingOrderAdminForm


class BillingOrderAdminFormTests(TestCase):
	def setUp(self):
		self.client_a = Client.objects.create(name="Client A")
		self.client_b = Client.objects.create(name="Client B")

	def _set_datetime(self, obj, field_name, dt):
		type(obj).objects.filter(pk=obj.pk).update(**{field_name: dt})
		# refresh from db to reflect changes
		obj.refresh_from_db()

	def test_order_queryset_filters_by_client_date_and_unbilled(self):
		base_time = timezone.now()

		# BillingRecord for client A
		br = BillingRecord.objects.create(
			client=self.client_a,
			amount=Decimal('100.00'),
			identifier='SER-001',
			folio='FOL-001',
		)
		self._set_datetime(br, 'date', base_time)

		# Orders
		order_a_before = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('10.00'),
		)
		self._set_datetime(order_a_before, 'order_date', base_time - timedelta(days=1))

		order_a_after_unbilled = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('20.00'),
		)
		self._set_datetime(order_a_after_unbilled, 'order_date', base_time + timedelta(hours=1))

		order_b_after_unbilled = Order.objects.create(
			client=self.client_b,
			total_amount=Decimal('30.00'),
		)
		self._set_datetime(order_b_after_unbilled, 'order_date', base_time + timedelta(hours=2))

		# An order already linked to ANY billing record should be excluded
		other_br = BillingRecord.objects.create(
			client=self.client_a,
			amount=Decimal('500.00'),
			identifier='SER-002',
			folio='FOL-002',
		)
		order_a_linked_elsewhere = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('40.00'),
		)
		self._set_datetime(order_a_linked_elsewhere, 'order_date', base_time + timedelta(hours=3))
		BillingOrder.objects.create(billing_record=other_br, order=order_a_linked_elsewhere)

		# Build form as inline with parent billing_record
		form = BillingOrderAdminForm(billing_record=br)
		qs = form.fields['order'].queryset

		self.assertIn(order_a_after_unbilled, qs)
		self.assertNotIn(order_a_before, qs)
		self.assertNotIn(order_b_after_unbilled, qs)
		self.assertNotIn(order_a_linked_elsewhere, qs)

	def test_order_queryset_includes_current_order_on_edit(self):
		base_time = timezone.now()

		br = BillingRecord.objects.create(
			client=self.client_a,
			amount=Decimal('100.00'),
			identifier='SER-003',
			folio='FOL-003',
		)
		self._set_datetime(br, 'date', base_time)

		current_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('50.00'),
		)
		self._set_datetime(current_order, 'order_date', base_time + timedelta(minutes=1))

		bo = BillingOrder.objects.create(billing_record=br, order=current_order)

		# Editing existing instance: form should include the current order even though it's linked
		form = BillingOrderAdminForm(instance=bo, billing_record=br)
		qs = form.fields['order'].queryset
		self.assertIn(current_order, qs)

	def test_validation_fails_when_sum_exceeds_billing_amount(self):
		br = BillingRecord.objects.create(
			client=self.client_a,
			amount=Decimal('100.00'),
			identifier='SER-004',
			folio='FOL-004',
		)

		existing_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('80.00'),
		)
		BillingOrder.objects.create(billing_record=br, order=existing_order)

		new_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('30.00'),
		)

		form = BillingOrderAdminForm(
			data={
				'billing_record': br.id,
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
		br = BillingRecord.objects.create(
			client=self.client_a,
			amount=Decimal('100.00'),
			identifier='SER-005',
			folio='FOL-005',
		)

		existing_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('80.00'),
		)
		BillingOrder.objects.create(billing_record=br, order=existing_order)

		new_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('20.00'),
		)

		form = BillingOrderAdminForm(
			data={
				'billing_record': br.id,
				'order': new_order.id,
				'is_paid': False,
				'partially_paid': False,
				'amount_paid': '0',
				'payment_date': '',
			}
		)

		self.assertTrue(form.is_valid())
