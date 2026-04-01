from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from clients.models import Client
from orders.models import Order
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
		order = SimpleNamespace(total_amount=Decimal('100.00'))
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
		order = SimpleNamespace(total_amount=Decimal('100.00'))
		user = SimpleNamespace(id=1)
		data = {'payment_method': 'cash', 'amount': '100.00'}

		result = services.process_payment_request(order=order, data=data, request_user=user)

		self.assertEqual(result, ({'success': True}, 200))
		process_legacy_mock.assert_called_once_with(
			order=order,
			data=data,
			request_user=user,
		)

class PaymentViewsIntegrationTests(TestCase):
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
		client = SimpleNamespace(
			balance=Decimal('100.00'),
			can_use_credit_for_payment=lambda: True,
			requires_note_for_credit_payment=lambda: False,
			validate_credit_payment=lambda amount, note: {'success': True},
		)
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
		payment_instance.save.assert_any_call(update_fields=['balance_used', 'credit_used', 'updated_at'], apply_accounting=False)
		payment_instance.link_pending_transaction_references.assert_called_once()
