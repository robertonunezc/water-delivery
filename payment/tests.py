from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

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
