from importlib import import_module
from decimal import Decimal
from datetime import date, timedelta
import json

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection
from django.forms.models import inlineformset_factory
from django.db.migrations.operations.base import Operation
from django.db.migrations.state import ProjectState
from django.test import TestCase, RequestFactory
from django.utils import timezone

from clients.models import Address, Client, InvoiceData
from clients.forms import InvoiceScheduleForm
from orders.models import Order
from invoice.models import Invoice, InvoiceOrderLink, InvoiceSchedule
from invoice.admin import InvoiceOrderLinkAdminForm, InvoiceOrderLinkAdmin
from invoice.models import Invoice, InvoiceOrderLink
from invoice.admin import (
	InvoiceAdmin,
	InvoiceOrderLinkAdmin,
	InvoiceOrderLinkAdminForm,
	InvoiceOrderLinkInlineFormSet,
)
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


class InvoiceCancellationModelTests(InvoiceTenantTestCase):
    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name='Invoice Cancellation Client',
            type='corporate',
        )
        self.invoice = Invoice.objects.create(
            client=self.client_obj,
            amount=Decimal('125.00'),
            identifier='CANCEL-TEST',
            folio='1',
        )

    def test_new_invoice_is_active(self) -> None:
        invoice = Invoice.objects.create(
            client=self.client_obj,
            amount=Decimal('125.00'),
            identifier='ACTIVE-TEST',
            folio='2',
        )

        self.assertEqual(getattr(invoice, 'status', None), 'ACTIVE')

    def test_cancel_invoice_marks_status_and_timestamp(self) -> None:
        from invoice import services

        cancel_invoice = getattr(services, 'cancel_invoice', lambda invoice: None)

        cancel_invoice(self.invoice)
        self.invoice.refresh_from_db()

        self.assertEqual(self.invoice.status, 'CANCELLED')
        self.assertIsNotNone(self.invoice.cancelled_at)
        self.assertEqual(self.invoice.pending_amount, 0)

    def test_cancelled_invoice_releases_orders_for_new_invoice(self) -> None:
        from invoice.services import cancel_invoice, get_invoiceable_orders_for_client

        order = Order.objects.create(
            client=self.client_obj,
            total_amount=Decimal('125.00'),
            status='COMPLETED',
        )
        InvoiceOrderLink.objects.create(invoice=self.invoice, order=order)

        cancel_invoice(self.invoice)

        invoiceable_orders = get_invoiceable_orders_for_client(self.client_obj)
        self.assertIn(order, invoiceable_orders)

    def test_order_from_cancelled_invoice_can_be_linked_to_new_invoice(self) -> None:
        from invoice.services import cancel_invoice, create_invoice_with_orders

        order = Order.objects.create(
            client=self.client_obj,
            total_amount=Decimal('125.00'),
            status='COMPLETED',
        )
        InvoiceOrderLink.objects.create(invoice=self.invoice, order=order)
        cancel_invoice(self.invoice)
        new_invoice = Invoice(
            client=self.client_obj,
            amount=Decimal('125.00'),
            identifier='NEW-AFTER-CANCEL',
            folio='2',
        )

        try:
            create_invoice_with_orders(invoice=new_invoice, orders=[order])
        except ValidationError as exc:
            self.fail(f'La factura cancelada todavía bloquea la venta: {exc}')

        self.assertEqual(new_invoice.status, 'ACTIVE')
        self.assertTrue(
            InvoiceOrderLink.objects.filter(invoice=new_invoice, order=order).exists()
        )

    def test_issued_invoice_fields_cannot_be_changed(self) -> None:
        self.invoice.amount = Decimal('999.00')

        with self.assertRaisesMessage(ValidationError, 'no se puede editar'):
            self.invoice.save()

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount, Decimal('125.00'))

    def test_issued_invoice_cannot_be_deleted(self) -> None:
        with self.assertRaisesMessage(ValidationError, 'debe cancelarse'):
            self.invoice.delete()

        self.assertTrue(Invoice.objects.filter(pk=self.invoice.pk).exists())


class InvoiceScheduleRecurrenceModelTests(InvoiceTenantTestCase):
    def setUp(self):
        self.client = Client.objects.create(
            name="Client With Billing Schedule",
            requires_billing=True,
            active=True,
        )

    def test_schedule_has_required_start_date_field(self):
        field_names = [field.name for field in InvoiceSchedule._meta.fields]

        self.assertIn("start_date", field_names)

        field = InvoiceSchedule._meta.get_field("start_date")
        self.assertFalse(field.null)
        self.assertFalse(field.blank)

    def test_clean_requires_start_date(self):
        schedule = InvoiceSchedule(
            client=self.client,
            frequency="monthly",
            billing_date="first_day",
            is_active=True,
        )
        schedule.start_date = None

        with self.assertRaises(ValidationError) as context:
            schedule.clean()

        self.assertIn("start_date", context.exception.message_dict)

    def test_weekly_clean_preserves_selected_weekday(self):
        schedule = InvoiceSchedule(
            client=self.client,
            frequency="weekly",
            weekday=2,
            is_active=True,
        )
        schedule.start_date = date(2026, 7, 13)

        schedule.clean()

        self.assertEqual(schedule.weekday, 2)
        self.assertIsNone(schedule.billing_date)
        self.assertIsNone(schedule.occurrence)
        self.assertIsNone(schedule.specific_day)

    def test_monthly_weekday_occurrence_requires_weekday(self):
        schedule = InvoiceSchedule(
            client=self.client,
            frequency="monthly",
            billing_date="weekday_occurrence",
            occurrence=1,
            is_active=True,
        )
        schedule.start_date = date(2026, 7, 13)

        with self.assertRaises(ValidationError) as context:
            schedule.clean()

        self.assertIn("weekday", context.exception.message_dict)


class InvoiceScheduleFormTests(InvoiceTenantTestCase):
    def test_form_exposes_required_start_date_without_monthly_ordinal_kind(self):
        form = InvoiceScheduleForm()

        self.assertIn("start_date", form.fields)
        self.assertTrue(form.fields["start_date"].required)
        self.assertNotIn("monthly_ordinal_day_kind", form.fields)


class InvoiceScheduleSchemaDriftMigrationTests(InvoiceTenantTestCase):
    obsolete_column = "monthly_ordinal_day_kind"
    table_name = "clients_clientbillingfrecuency"

    def test_obsolete_monthly_ordinal_column_is_made_nullable_by_migration(self) -> None:
        operation = self._load_relax_column_operation()
        self._add_obsolete_column()

        self.assertEqual(self._obsolete_column_nullability(), "NO")

        with connection.schema_editor() as schema_editor:
            operation.database_forwards(
                "billing",
                schema_editor,
                ProjectState(),
                ProjectState(),
            )

        self.assertEqual(self._obsolete_column_nullability(), "YES")
        client = Client.objects.create(
            name="Schedule Schema Drift Client",
            requires_billing=True,
            active=True,
        )
        InvoiceSchedule.objects.create(
            client=client,
            frequency="monthly",
            billing_date="last_day",
            start_date=date(2026, 8, 2),
            is_active=True,
        )

    def _load_relax_column_operation(self) -> Operation:
        migration_path = (
            "invoice.migrations.0023_relax_obsolete_monthly_ordinal_day_kind"
        )
        try:
            migration_module = import_module(migration_path)
        except ModuleNotFoundError as exc:
            if exc.name != migration_path:
                raise
            self.fail(
                "Expected billing migration to relax obsolete "
                "monthly_ordinal_day_kind column constraint."
            )

        return migration_module.Migration.operations[0]

    def _add_obsolete_column(self) -> None:
        table_name = connection.ops.quote_name(self.table_name)
        column_name = connection.ops.quote_name(self.obsolete_column)

        with connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS {column_name}"
            )
            cursor.execute(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} varchar(50) NOT NULL DEFAULT 'legacy'"
            )
            cursor.execute(
                f"ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP DEFAULT"
            )

    def _obsolete_column_nullability(self) -> str | None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s
                  AND column_name = %s
                """,
                [self.table_name, self.obsolete_column],
            )
            row = cursor.fetchone()
            return row[0] if row else None


class BillingOrderAdminFormTests(InvoiceTenantTestCase):
		def setUp(self):
			self.client_a = Client.objects.create(name="Client A", type='corporate')
			self.client_b = Client.objects.create(name="Client B", type='corporate')

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

		def test_invoice_for_corporate_can_select_branch_order(self):
			branch = Client.objects.create(
				name='Client A Branch',
				type='branch',
				corporate=self.client_a,
			)
			invoice = Invoice.objects.create(
				client=self.client_a,
				amount=Decimal('100.00'),
				identifier='SER-BR-001',
				folio='FOL-BR-001',
			)
			branch_order = Order.objects.create(
				client=branch,
				total_amount=Decimal('40.00'),
				status='COMPLETED',
			)

			form = InvoiceOrderLinkAdminForm(invoice=invoice)

			self.assertIn(branch_order, form.fields['order'].queryset)

		def test_add_order_to_invoice_rejects_order_from_different_fiscal_owner(self):
			from django.core.exceptions import ValidationError
			from invoice.services import add_order_to_invoice

			other_corporate = Client.objects.create(name='Other Corporate', type='corporate')
			other_branch = Client.objects.create(
				name='Other Branch',
				type='branch',
				corporate=other_corporate,
			)
			invoice = Invoice.objects.create(
				client=self.client_a,
				amount=Decimal('100.00'),
				identifier='SER-BR-002',
				folio='FOL-BR-002',
			)
			other_order = Order.objects.create(
				client=other_branch,
				total_amount=Decimal('40.00'),
				status='COMPLETED',
			)

			with self.assertRaisesMessage(ValidationError, 'cliente fiscal'):
				add_order_to_invoice(invoice=invoice, order=other_order)

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
		self.client_a = Client.objects.create(name='Client A', type='corporate')

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

	def test_fiscal_owner_scope_includes_corporate_and_branch_orders(self):
		from invoice.services import get_invoiceable_orders_for_client

		corporate = Client.objects.create(name='Fiscal Corp', type='corporate')
		branch = Client.objects.create(name='Fiscal Branch', type='branch', corporate=corporate)
		corporate_order = Order.objects.create(
			client=corporate,
			total_amount=Decimal('10.00'),
			status='COMPLETED',
		)
		branch_order = Order.objects.create(
			client=branch,
			total_amount=Decimal('20.00'),
			status='COMPLETED',
		)

		qs = get_invoiceable_orders_for_client(client=corporate, scope='fiscal_owner')

		self.assertIn(corporate_order, qs)
		self.assertIn(branch_order, qs)

	def test_exact_scope_keeps_existing_single_client_filter(self):
		from invoice.services import get_invoiceable_orders_for_client

		corporate = Client.objects.create(name='Exact Corp', type='corporate')
		branch = Client.objects.create(name='Exact Branch', type='branch', corporate=corporate)
		branch_order = Order.objects.create(
			client=branch,
			total_amount=Decimal('20.00'),
			status='COMPLETED',
		)

		qs = get_invoiceable_orders_for_client(client=corporate, scope='exact')

		self.assertNotIn(branch_order, qs)


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

	def test_branch_order_invoice_is_issued_to_corporate(self):
		from invoice.services import create_invoice_from_orders

		branch = Client.objects.create(
			name='Client A Branch',
			type='branch',
			corporate=self.client_a,
		)
		order = self._completed_order(branch, '50.00')

		invoice = create_invoice_from_orders(orders=[order], client=branch)

		self.assertEqual(invoice.client, self.client_a)
		self.assertEqual(invoice.invoice_links.get().order, order)

	def test_multi_branch_invoice_is_issued_to_shared_corporate(self):
		from invoice.services import create_invoice_from_orders

		branch_one = Client.objects.create(name='Branch One', type='branch', corporate=self.client_a)
		branch_two = Client.objects.create(name='Branch Two', type='branch', corporate=self.client_a)
		order_one = self._completed_order(branch_one, '25.00')
		order_two = self._completed_order(branch_two, '35.00')

		invoice = create_invoice_from_orders(orders=[order_one, order_two], client=branch_one)

		self.assertEqual(invoice.client, self.client_a)
		self.assertEqual(invoice.amount, Decimal('60.00'))

	def test_rejects_branch_without_corporate(self):
		from django.core.exceptions import ValidationError
		from invoice.services import create_invoice_from_orders

		branch = Client.objects.create(name='Orphan Branch', type='branch')
		order = self._completed_order(branch, '10.00')

		with self.assertRaisesMessage(ValidationError, 'corporativo'):
			create_invoice_from_orders(orders=[order], client=branch)

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


class CreateInvoiceWithOrdersServiceTests(InvoiceTenantTestCase):
	def setUp(self):
		self.client_obj = Client.objects.create(
			name='Manual Invoice Client',
			type='corporate',
		)

	def test_saves_invoice_and_links_orders(self):
		from invoice.services import create_invoice_with_orders

		order = Order.objects.create(
			client=self.client_obj,
			total_amount=Decimal('50.00'),
			status='COMPLETED',
		)
		invoice = Invoice(
			client=self.client_obj,
			amount=Decimal('75.00'),
			identifier='MANUAL-WITH-ORDER',
			folio='MANUAL-WITH-ORDER',
		)

		created_invoice = create_invoice_with_orders(
			invoice=invoice,
			orders=[order],
		)

		self.assertIsNotNone(created_invoice.pk)
		self.assertEqual(created_invoice.invoice_links.get().order, order)

	def test_rejects_empty_orders_without_saving_invoice(self):
		from invoice.services import create_invoice_with_orders

		invoice = Invoice(
			client=self.client_obj,
			amount=Decimal('75.00'),
			identifier='MANUAL-NO-ORDERS',
			folio='MANUAL-NO-ORDERS',
		)

		with self.assertRaisesMessage(ValidationError, 'al menos una venta'):
			create_invoice_with_orders(invoice=invoice, orders=[])

		self.assertIsNone(invoice.pk)
		self.assertFalse(Invoice.objects.filter(identifier='MANUAL-NO-ORDERS').exists())

	def test_rejects_orders_exceeding_manual_invoice_amount(self):
		from invoice.services import create_invoice_with_orders

		order = Order.objects.create(
			client=self.client_obj,
			total_amount=Decimal('80.00'),
			status='COMPLETED',
		)
		invoice = Invoice(
			client=self.client_obj,
			amount=Decimal('75.00'),
			identifier='MANUAL-OVER-CAP',
			folio='MANUAL-OVER-CAP',
		)

		with self.assertRaisesMessage(ValidationError, 'excede el monto'):
			create_invoice_with_orders(invoice=invoice, orders=[order])

		self.assertIsNone(invoice.pk)
		self.assertFalse(Invoice.objects.filter(identifier='MANUAL-OVER-CAP').exists())


class CustomAdminInvoiceViewsTests(InvoiceTenantTestCase):
	def setUp(self):
		super().setUp()
		self.superuser = User.objects.create_superuser(username='admin_staff', password='pass_staff')
		self.client_obj = Client.objects.create(name='Test Client A', type='corporate')
		self.invoice = Invoice.objects.create(
			client=self.client_obj,
			amount=Decimal('200.00'),
			identifier='SER-T1',
			folio='FOL-T1',
			auto_amount=False
		)
		self.client.force_login(self.superuser)

	def _completed_order(self, client, amount='50.00'):
		return Order.objects.create(
			client=client,
			total_amount=Decimal(amount),
			status='COMPLETED',
		)

	def test_cancel_invoice_admin_view_marks_invoice_cancelled(self):
		url = f'/administrador/facturas/{self.invoice.pk}/cancelar/'

		response = self.client.post(url)

		self.assertEqual(response.status_code, 302)
		self.invoice.refresh_from_db()
		self.assertEqual(self.invoice.status, 'CANCELLED')
		self.assertIsNotNone(self.invoice.cancelled_at)

	def test_invoice_detail_rejects_edits(self):
		url = reverse('admin_edit_invoice', args=[self.invoice.pk])

		response = self.client.post(url, {'amount': '999.00'})

		self.assertEqual(response.status_code, 405)
		self.invoice.refresh_from_db()
		self.assertEqual(self.invoice.amount, Decimal('200.00'))

	def test_invoice_detail_renders_read_only_state(self):
		url = reverse('admin_edit_invoice', args=[self.invoice.pk])

		response = self.client.get(url)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'ACTIVA')
		self.assertNotContains(response, 'name="amount"')
		self.assertNotContains(response, 'Vincular Nueva Venta')

	def test_invoice_list_shows_status_and_cancel_action(self):
		cancelled_invoice = Invoice.objects.create(
			client=self.client_obj,
			amount=Decimal('75.00'),
			identifier='SER-CANCELLED',
			folio='FOL-CANCELLED',
			status='CANCELLED',
			cancelled_at=timezone.now(),
		)

		response = self.client.get(reverse('admin_invoices'))

		self.assertContains(response, 'ACTIVA')
		self.assertContains(response, 'CANCELADA')
		self.assertContains(
			response,
			reverse('admin_cancel_invoice', args=[self.invoice.pk]),
		)
		self.assertNotContains(
			response,
			reverse('admin_cancel_invoice', args=[cancelled_invoice.pk]),
		)

	def test_client_invoice_list_shows_status_and_cancel_action(self):
		self.client_obj.requires_billing = True
		self.client_obj.save(update_fields=['requires_billing'])
		active_order = self._completed_order(self.client_obj, '200.00')
		InvoiceOrderLink.objects.create(invoice=self.invoice, order=active_order)
		cancelled_invoice = Invoice.objects.create(
			client=self.client_obj,
			amount=Decimal('75.00'),
			identifier='CLIENT-CANCELLED',
			folio='1',
			status='CANCELLED',
			cancelled_at=timezone.now(),
		)
		cancelled_order = self._completed_order(self.client_obj, '75.00')
		InvoiceOrderLink.objects.create(
			invoice=cancelled_invoice,
			order=cancelled_order,
		)

		url = reverse('clients:detail', args=[self.client_obj.pk])
		response = self.client.get(f'{url}?tab=invoices')

		self.assertContains(response, 'ACTIVA')
		self.assertContains(response, 'CANCELADA')
		self.assertContains(response, '1 factura pendiente')
		self.assertContains(
			response,
			reverse('admin_cancel_invoice', args=[self.invoice.pk]),
		)
		self.assertNotContains(
			response,
			reverse('admin_cancel_invoice', args=[cancelled_invoice.pk]),
		)

	def test_create_invoice_admin_view_requires_linked_orders(self):
		url = reverse('admin_create_invoice')
		data = {
			'client': self.client_obj.id,
			'identifier': 'SER-NO-ORDERS',
			'folio': 'FOL-NO-ORDERS',
			'amount': '150.00',
			'auto_amount': False,
		}

		response = self.client.post(url, data)

		self.assertEqual(response.status_code, 200)
		self.assertFormError(
			response.context['form'],
			'orders',
			'Debe vincular al menos una venta para crear la factura.',
		)
		self.assertFalse(Invoice.objects.filter(identifier='SER-NO-ORDERS').exists())

	def test_create_invoice_admin_view_post(self):
		order = self._completed_order(self.client_obj)
		url = reverse('admin_create_invoice')
		data = {
			'client': self.client_obj.id,
			'identifier': 'SER-NEW',
			'folio': 'FOL-NEW',
			'amount': '150.00',
			'auto_amount': False,
			'orders': [order.id],
		}
		response = self.client.post(url, data)
		self.assertEqual(response.status_code, 302) # Redirect to edit page
		invoice = Invoice.objects.get(identifier='SER-NEW')
		self.assertTrue(
			InvoiceOrderLink.objects.filter(invoice=invoice, order=order).exists()
		)

	def test_create_invoice_admin_view_post_branch_uses_corporate(self):
		branch = Client.objects.create(
			name='Branch Invoice Client',
			type='branch',
			corporate=self.client_obj,
		)
		order = self._completed_order(branch)
		url = reverse('admin_create_invoice')
		data = {
			'client': branch.id,
			'identifier': 'SER-BRANCH',
			'folio': 'FOL-BRANCH',
			'amount': '150.00',
			'auto_amount': False,
			'orders': [order.id],
		}

		response = self.client.post(url, data)

		self.assertEqual(response.status_code, 302)
		invoice = Invoice.objects.get(identifier='SER-BRANCH')
		self.assertEqual(invoice.client, self.client_obj)
		self.assertEqual(invoice.invoice_links.get().order, order)

	def test_invoice_detail_does_not_allow_linking_orders(self):
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
		self.assertEqual(response.status_code, 405)
		self.assertFalse(
			InvoiceOrderLink.objects.filter(
				invoice=self.invoice,
				order=order,
			).exists()
		)


class InvoiceAdminSaveModelTests(InvoiceTenantTestCase):
	def setUp(self):
		super().setUp()
		self.superuser = User.objects.create_superuser(username='invoice_admin', password='pass_staff')
		self.factory = RequestFactory()
		self.invoice_admin = InvoiceAdmin(Invoice, admin.site)
		self.corporate = Client.objects.create(name='Admin Corporate', type='corporate')

	def test_save_model_normalizes_branch_client_to_corporate_on_create(self):
		branch = Client.objects.create(
			name='Admin Branch',
			type='branch',
			corporate=self.corporate,
		)
		request = self.factory.post('/admin/billing/invoice/add/')
		request.user = self.superuser
		invoice = Invoice(
			client=branch,
			amount=Decimal('75.00'),
			identifier='ADM-BRANCH',
			folio='ADM-BRANCH',
		)

		class FormStub:
			changed_data = ['client']

		self.invoice_admin.save_model(request, invoice, FormStub(), change=False)

		invoice.refresh_from_db()
		self.assertEqual(invoice.client, self.corporate)

	def test_admin_existing_invoice_is_read_only(self):
		invoice = Invoice.objects.create(
			client=self.corporate,
			amount=Decimal('75.00'),
			identifier='ADM-READONLY',
			folio='1',
		)
		request = self.factory.get(f'/admin/billing/invoice/{invoice.pk}/change/')
		request.user = self.superuser

		self.assertFalse(
			self.invoice_admin.has_change_permission(request, invoice)
		)
		self.assertEqual(
			self.invoice_admin.get_inline_instances(request, invoice),
			[],
		)

	def test_add_form_requires_at_least_one_order_inline(self):
		formset_class = inlineformset_factory(
			Invoice,
			InvoiceOrderLink,
			formset=InvoiceOrderLinkInlineFormSet,
			fields=('order', 'is_paid', 'partially_paid'),
			extra=0,
			can_delete=True,
		)
		invoice = Invoice(
			client=self.corporate,
			amount=Decimal('75.00'),
			identifier='ADM-NO-ORDERS',
			folio='ADM-NO-ORDERS',
		)
		formset = formset_class(
			data={
				'invoice_links-TOTAL_FORMS': '0',
				'invoice_links-INITIAL_FORMS': '0',
				'invoice_links-MIN_NUM_FORMS': '0',
				'invoice_links-MAX_NUM_FORMS': '1000',
			},
			instance=invoice,
			prefix='invoice_links',
		)

		self.assertFalse(formset.is_valid())
		self.assertIn(
			'Debe vincular al menos una venta para crear la factura.',
			formset.non_form_errors(),
		)


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
		Invoice.objects.create(
			client=self.client_b,
			amount=Decimal('900.00'),
			identifier='BAL-CANCELLED',
			folio='BAL-CANCELLED',
			status='CANCELLED',
			cancelled_at=timezone.now(),
		)

		snapshot = get_invoice_balance_snapshot()

		self.assertEqual(snapshot["available_capacity_count"], 1)
		self.assertEqual(snapshot["available_capacity_total"], Decimal("200.00"))
		self.assertEqual(snapshot["unpaid_balance_count"], 1)
		self.assertEqual(snapshot["unpaid_balance_total"], Decimal("400.00"))
