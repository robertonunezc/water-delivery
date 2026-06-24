from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase
from django.urls import reverse
from tenant_client.test_utils import FastTenantTestCase

User = get_user_model()

from clients.models import Client
from orders.models import Order
from payment.models import Payment
from payment import services


class PaymentServicesTests(SimpleTestCase):
	def test_apply_cantidad_cobrada_none_returns_zero_balance_added(self):
		order = SimpleNamespace(total_amount=Decimal('100.00'))
		user = SimpleNamespace(id=1)

		result = services.apply_cantidad_cobrada(order, None, user)

		self.assertIsNone(result['cantidad_cobrada'])
		self.assertEqual(result['balance_added'], Decimal('0.00'))

	def test_apply_cantidad_cobrada_raises_when_less_than_order_total(self):
		order = SimpleNamespace(total_amount=Decimal('100.00'))
		user = SimpleNamespace(id=1)

		with self.assertRaises(ValueError):
			services.apply_cantidad_cobrada(order, '99.99', user)

	@patch('payment.services.balance_service.add_balance')
	def test_apply_cantidad_cobrada_adds_balance_on_excess(self, add_balance_mock):
		client = SimpleNamespace(balance=Decimal('50.00'))
		order = SimpleNamespace(id=10, total_amount=Decimal('100.00'), client=client)
		user = SimpleNamespace(id=1)

		result = services.apply_cantidad_cobrada(order, '120.00', user)

		self.assertEqual(result['cantidad_cobrada'], Decimal('120.00'))
		self.assertEqual(result['balance_added'], Decimal('20.00'))
		self.assertEqual(order.cantidad_cobrada, Decimal('120.00'))
		add_balance_mock.assert_called_once()

	@patch('payment.services.process_multiple_payments')
	def test_process_payment_request_routes_to_multiple(self, process_multiple_mock):
		process_multiple_mock.return_value = ({'success': True}, 200)
		order = SimpleNamespace(total_amount=Decimal('100.00'), type='contado')
		user = SimpleNamespace(id=1)
		data = {
			'payments': [{'amount': '100.00', 'payment_method': 'cash'}],
			'cantidad_cobrada': '100.00',
		}

		result = services.process_payment_request(order=order, data=data, request_user=user)

		self.assertEqual(result, ({'success': True}, 200))
		process_multiple_mock.assert_called_once_with(
			order=order,
			payments_data=data['payments'],
			cantidad_cobrada='100.00',
			request_user=user,
		)

	@patch('payment.services.process_legacy_payment')
	def test_process_payment_request_routes_to_legacy(self, process_legacy_mock):
		process_legacy_mock.return_value = ({'success': True}, 200)
		order = SimpleNamespace(total_amount=Decimal('100.00'), type='contado')
		user = SimpleNamespace(id=1)
		data = {'payment_method': 'cash', 'amount': '100.00'}

		result = services.process_payment_request(order=order, data=data, request_user=user)

		self.assertEqual(result, ({'success': True}, 200))
		process_legacy_mock.assert_called_once_with(
			order=order,
			data=data,
			request_user=user,
		)

	@patch('payment.services._process_credit_order_flow')
	def test_process_payment_request_routes_credit_orders(self, credit_flow_mock):
		credit_flow_mock.return_value = ({'success': True, 'order_pending_credit': True}, 200)
		order = SimpleNamespace(total_amount=Decimal('100.00'), type='credito')
		user = SimpleNamespace(id=1)

		result = services.process_payment_request(order=order, data={}, request_user=user)

		self.assertEqual(result, ({'success': True, 'order_pending_credit': True}, 200))
		credit_flow_mock.assert_called_once_with(order=order, data={}, request_user=user)

class PaymentViewsIntegrationTests(FastTenantTestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='tester', password='testpass123')
		self.client.force_login(self.user)

		self.customer = Client.objects.create(
			name='Cliente Test Endpoint',
			type='corporate',
		)
		self.order = Order.objects.create(
			client=self.customer,
			total_amount=Decimal('120.00'),
		)

	@patch('payment.views.payment_services.process_payment_request')
	def test_create_payment_delegates_to_service(self, process_request_mock):
		process_request_mock.return_value = ({'success': True, 'payment_count': 1}, 200)

		payload = {
			'order_id': self.order.id,
			'payments': [{'amount': '120.00', 'payment_method': 'cash'}],
		}
		response = self.client.post(
			reverse('payment:create_payment'),
			data=payload,
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), {'success': True, 'payment_count': 1})
		process_request_mock.assert_called_once()

		kwargs = process_request_mock.call_args.kwargs
		self.assertEqual(kwargs['order'].id, self.order.id)
		self.assertEqual(kwargs['data'], payload)
		self.assertEqual(kwargs['request_user'].id, self.user.id)

	@patch('payment.services.Payment')
	def test_process_single_payment_uses_explicit_accounting_flow(self, payment_cls_mock):
		client = SimpleNamespace(balance=Decimal('100.00'))
		order = SimpleNamespace(client=client)
		user = SimpleNamespace(id=1)

		payment_instance = payment_cls_mock.return_value
		payment_instance.status = 'completed'

		payment, error = services.process_single_payment(
			order=order,
			payment_method='cash',
			amount=Decimal('10.00'),
			request_user=user,
		)

		self.assertIsNone(error)
		self.assertEqual(payment, payment_instance)
		payment_instance.save.assert_any_call(apply_accounting=False)
		payment_instance.apply_accounting_side_effects.assert_called_once()
		payment_instance.save.assert_any_call(update_fields=['balance_used', 'updated_at'], apply_accounting=False)
		payment_instance.link_pending_transaction_references.assert_called_once()


class CreditOrderSettlementTests(FastTenantTestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username='credit-settlement-user',
			password='testpass123',
		)
		self.customer = Client.objects.create(
			name='Cliente con crédito pendiente',
			type='corporate',
			credit_limit=Decimal('1000.00'),
			current_debt=Decimal('1000.00'),
			can_pay_with_credit=True,
		)
		self.order = Order.objects.create(
			client=self.customer,
			total_amount=Decimal('1000.00'),
			type='credito',
		)
		self.pending_credit = Payment(
			amount=Decimal('1000.00'),
			method='pending_credit',
			status='pending',
			client=self.customer,
			order=self.order,
			created_by=self.user,
		)
		self.pending_credit.save(apply_accounting=False)
		self.client.force_login(self.user)

	def test_settlement_reduces_debt_and_restores_available_credit(self):
		payment, error = services.settle_credit_order_payment(
			order=self.order,
			payment_method='cash',
			amount=Decimal('1000.00'),
			request_user=self.user,
		)

		self.assertIsNone(error)
		self.assertEqual(payment.method, 'cash')
		self.customer.refresh_from_db()
		self.pending_credit.refresh_from_db()
		self.assertEqual(self.customer.current_debt, Decimal('0.00'))
		self.assertEqual(self.customer.get_available_credit(), 1000.0)
		self.assertEqual(self.pending_credit.status, 'completed')
		self.assertTrue(Order.objects.paid().filter(pk=self.order.pk).exists())

	def test_reconciliation_applies_existing_payment_without_duplicate(self):
		existing_payment = Payment(
			amount=Decimal('1000.00'),
			method='cash',
			status='completed',
			client=self.customer,
			order=self.order,
			created_by=self.user,
		)
		existing_payment.save(apply_accounting=False)

		payment, error = services.settle_credit_order_payment(
			order=self.order,
			payment_method='cash',
			amount=Decimal('1000.00'),
			request_user=self.user,
		)

		self.assertIsNone(error)
		self.assertEqual(payment.pk, existing_payment.pk)
		self.assertEqual(
			self.order.payments.filter(method='cash').count(),
			1,
		)
		self.customer.refresh_from_db()
		self.assertEqual(self.customer.current_debt, Decimal('0.00'))

	def test_mismatched_existing_payment_requires_manual_review(self):
		existing_payment = Payment(
			amount=Decimal('900.00'),
			method='cash',
			status='completed',
			client=self.customer,
			order=self.order,
			created_by=self.user,
		)
		existing_payment.save(apply_accounting=False)

		with self.assertRaisesRegex(ValueError, 'revisión manual'):
			services.settle_credit_order_payment(
				order=self.order,
				payment_method='cash',
				amount=Decimal('1000.00'),
				request_user=self.user,
			)

		self.customer.refresh_from_db()
		self.assertEqual(self.customer.current_debt, Decimal('1000.00'))
		self.assertEqual(self.order.payments.filter(method='cash').count(), 1)

	def test_wrong_settlement_amount_does_not_create_payment(self):
		payment, error = services.settle_credit_order_payment(
			order=self.order,
			payment_method='cash',
			amount=Decimal('900.00'),
			request_user=self.user,
		)

		self.assertIsNone(payment)
		self.assertIn('debe cubrir el saldo pendiente', error['error'])
		self.assertFalse(self.order.payments.filter(method='cash').exists())

	def test_completed_pending_marker_is_not_counted_as_money_paid(self):
		self.pending_credit.status = 'completed'
		self.pending_credit.save(
			update_fields=['status', 'updated_at'],
			apply_accounting=False,
		)

		self.assertEqual(self.order.total_paid, Decimal('0.00'))
		self.assertTrue(Order.objects.unpaid().filter(pk=self.order.pk).exists())

	def test_order_payment_endpoint_reduces_credit_debt(self):
		response = self.client.post(
			reverse('orders:create_payment_for_order', args=[self.order.pk]),
			data={
				'amount': '1000.00',
				'payment_method': 'cash',
			},
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		self.customer.refresh_from_db()
		self.assertEqual(self.customer.current_debt, Decimal('0.00'))
		self.assertEqual(self.customer.get_available_credit(), 1000.0)

class MigrateLegacyCreditOrdersCommandTests(FastTenantTestCase):
	def setUp(self):
		self.customer = Client.objects.create(
			name='Cliente Crédito',
			credit_limit=Decimal('500.00'),
		)

	def test_command_migrates_single_legacy_credit_payment(self):
		order = Order.objects.create(
			client=self.customer,
			total_amount=Decimal('120.00'),
			type='contado',
		)
		payment = Payment(
			amount=Decimal('120.00'),
			method='credit',
			status='completed',
			client=self.customer,
			order=order,
		)
		payment.save(apply_accounting=False)

		stdout = StringIO()
		call_command('migrate_legacy_credit_orders', '--apply', stdout=stdout)

		order.refresh_from_db()
		payment.refresh_from_db()

		self.assertEqual(order.type, 'credito')
		self.assertEqual(payment.method, 'pending_credit')
		self.assertEqual(payment.status, 'pending')
		self.assertIn('Orders migrated: 1', stdout.getvalue())

	def test_command_dry_run_leaves_records_unchanged(self):
		order = Order.objects.create(
			client=self.customer,
			total_amount=Decimal('80.00'),
			type='contado',
		)
		payment = Payment(
			amount=Decimal('80.00'),
			method='credit',
			status='completed',
			client=self.customer,
			order=order,
		)
		payment.save(apply_accounting=False)

		stdout = StringIO()
		call_command('migrate_legacy_credit_orders', stdout=stdout)

		order.refresh_from_db()
		payment.refresh_from_db()

		self.assertEqual(order.type, 'contado')
		self.assertEqual(payment.method, 'credit')
		self.assertEqual(payment.status, 'completed')
		self.assertIn('Dry run mode. No changes will be written.', stdout.getvalue())
