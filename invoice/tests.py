from decimal import Decimal
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from clients.models import Address, Client, InvoiceData
from orders.models import Order
from invoice.models import Invoice, InvoiceOrderLink, InvoiceSchedule
from tenant_client.test_utils import FastTenantTestCase


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

	def test_draft_invoice_reserves_linked_order(self):
		from invoice.services import get_invoiceable_orders_for_client

		order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('20.00'),
			status='COMPLETED',
		)
		draft = Invoice.objects.create(
			client=self.client_a,
			amount=Decimal('20.00'),
			identifier='BORRADOR-RESERVA',
			folio='BORRADOR-RESERVA',
			status='DRAFT',
		)
		InvoiceOrderLink.objects.create(invoice=draft, order=order)

		qs = get_invoiceable_orders_for_client(client=self.client_a)

		self.assertNotIn(order, qs)

	def test_editable_draft_orders_include_current_and_available_orders(self):
		from invoice.services import get_editable_orders_for_invoice
		from payment.models import Payment

		current_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('20.00'),
			status='COMPLETED',
		)
		available_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('30.00'),
			status='COMPLETED',
		)
		for order in (current_order, available_order):
			Payment.objects.create(
				client=self.client_a,
				order=order,
				amount=order.total_amount,
				method='cash',
				status='completed',
			)
		draft = Invoice.objects.create(
			client=self.client_a,
			amount=Decimal('20.00'),
			identifier='BORRADOR-EDITABLE',
			folio='BORRADOR-EDITABLE',
			status='DRAFT',
		)
		InvoiceOrderLink.objects.create(invoice=draft, order=current_order)

		order_ids = set(
			get_editable_orders_for_invoice(draft).values_list('id', flat=True)
		)

		self.assertSetEqual(
			order_ids,
			{current_order.pk, available_order.pk},
		)

	def test_editable_draft_orders_only_include_completed_fully_paid_orders(self):
		from invoice.services import get_editable_orders_for_invoice
		from payment.models import Payment

		paid_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('30.00'),
			status='COMPLETED',
		)
		Payment.objects.create(
			client=self.client_a,
			order=paid_order,
			amount=Decimal('30.00'),
			method='cash',
			status='completed',
		)
		unpaid_current_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('40.00'),
			status='COMPLETED',
		)
		unpaid_available_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('50.00'),
			status='COMPLETED',
		)
		pending_paid_order = Order.objects.create(
			client=self.client_a,
			total_amount=Decimal('60.00'),
			status='PENDING',
		)
		Payment.objects.create(
			client=self.client_a,
			order=pending_paid_order,
			amount=Decimal('60.00'),
			method='cash',
			status='completed',
		)
		draft = Invoice.objects.create(
			client=self.client_a,
			amount=unpaid_current_order.total_amount,
			identifier='BORRADOR-PAGADAS',
			folio='BORRADOR-PAGADAS',
			status='DRAFT',
		)
		InvoiceOrderLink.objects.create(
			invoice=draft,
			order=unpaid_current_order,
		)

		order_ids = set(
			get_editable_orders_for_invoice(draft).values_list('id', flat=True)
		)

		self.assertSetEqual(order_ids, {paid_order.pk})


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
		self.assertEqual(invoice.status, 'DRAFT')

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

	def test_rejects_order_reserved_by_another_draft(self):
		from invoice.services import create_invoice_from_orders

		order = self._completed_order(self.client_a, '40.00')
		create_invoice_from_orders(orders=[order], client=self.client_a)

		with self.assertRaisesMessage(ValidationError, 'otra factura'):
			create_invoice_from_orders(orders=[order], client=self.client_a)

		self.assertEqual(
			Invoice.objects.filter(invoice_links__order=order).count(),
			1,
		)

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


class InvoiceDraftServiceTests(InvoiceTenantTestCase):
    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name='Draft Invoice Client',
            type='corporate',
        )
        self.linked_order = self._completed_order('50.00')
        self.replacement_order = self._completed_order('80.00')
        self.draft = Invoice.objects.create(
            client=self.client_obj,
            amount=self.linked_order.total_amount,
            identifier='BORRADOR-EDIT',
            folio='BORRADOR-EDIT',
            auto_amount=True,
            status='DRAFT',
        )
        InvoiceOrderLink.objects.create(
            invoice=self.draft,
            order=self.linked_order,
        )

    def _completed_order(self, amount: str) -> Order:
        return Order.objects.create(
            client=self.client_obj,
            total_amount=Decimal(amount),
            status='COMPLETED',
        )

    def test_issuing_draft_replaces_orders_and_locks_invoice(self) -> None:
        from invoice.services import issue_draft_invoice

        self.draft.identifier = 'FE'
        self.draft.folio = '600190'
        self.draft.emmited_at = date(2026, 9, 26)

        invoice = issue_draft_invoice(
            invoice=self.draft,
            orders=[self.replacement_order],
        )

        self.assertEqual(invoice.identifier, 'FE')
        self.assertEqual(invoice.folio, '600190')
        self.assertEqual(invoice.emmited_at, date(2026, 9, 26))
        self.assertEqual(invoice.amount, Decimal('80.00'))
        self.assertEqual(invoice.status, 'ACTIVE')
        self.assertSetEqual(
            set(invoice.invoice_links.values_list('order_id', flat=True)),
            {self.replacement_order.pk},
        )

        invoice.identifier = 'FE-CHANGED'
        with self.assertRaisesMessage(
            ValidationError,
            'Solo las facturas en borrador se pueden modificar.',
        ):
            issue_draft_invoice(invoice=invoice, orders=[self.replacement_order])

        invoice.refresh_from_db()
        self.assertEqual(invoice.identifier, 'FE')


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
