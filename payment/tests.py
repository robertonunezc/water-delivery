from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.utils import timezone
from tenant_client.test_utils import FastTenantTestCase

User = get_user_model()

from clients.models import Client, ClientCreditConfig, CreditTransaction
from clients.services import balance_service
from clients.services.pending_payment_service import client_has_overdue_credit
from orders.models import Order, OrderStatus
from payment.models import Payment
from payment import services
from payment.services import PaymentRequestData


class PaymentServicesTests(SimpleTestCase):
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
		payment_date = date(2026, 7, 14)

		result = services.apply_cantidad_cobrada(
			order,
			'120.00',
			user,
			payment_date=payment_date,
		)

		self.assertEqual(result['cantidad_cobrada'], Decimal('120.00'))
		self.assertEqual(result['balance_added'], Decimal('20.00'))
		self.assertEqual(order.cantidad_cobrada, Decimal('120.00'))
		add_balance_mock.assert_called_once()
		add_balance_date = add_balance_mock.call_args.kwargs['date']
		self.assertEqual(timezone.localtime(add_balance_date).date(), payment_date)

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

	def test_balance_settlement_records_payment_from_balance_credit_transaction(self):
		self.customer.balance = Decimal('1000.00')
		self.customer.save(update_fields=['balance', 'updated_at'])

		payment, error = services.settle_credit_order_payment(
			order=self.order,
			payment_method='balance',
			amount=Decimal('1000.00'),
			request_user=self.user,
			payment_client=self.customer,
		)

		self.assertIsNone(error)
		self.assertEqual(payment.method, 'balance')
		self.assertTrue(
			CreditTransaction.objects.filter(
				client=self.customer,
				reference_order=self.order,
				reference_payment=payment,
				transaction_type='payment_from_balance',
				amount=Decimal('1000.00'),
			).exists()
		)

	def test_pay_client_orders_rejects_balance_overpayment(self):
		self.customer.balance = Decimal('1200.00')
		self.customer.save(update_fields=['balance', 'updated_at'])

		with self.assertRaisesRegex(
			services.ClientOrderPaymentError,
			'Pago con saldo debe coincidir',
		):
			services.pay_client_orders(
				client=self.customer,
				orders=[self.order],
				payment_method='balance',
				amount=Decimal('1100.00'),
				request_user=self.user,
				payment_client=self.customer,
			)

		self.customer.refresh_from_db()
		self.pending_credit.refresh_from_db()
		self.assertEqual(self.customer.current_debt, Decimal('1000.00'))
		self.assertEqual(self.customer.balance, Decimal('1200.00'))
		self.assertEqual(self.pending_credit.status, 'pending')
		self.assertFalse(self.order.payments.filter(method='balance').exists())

	def test_pay_client_orders_rejects_credit_order_without_pending_marker(self):
		self.pending_credit.status = 'completed'
		self.pending_credit.save(
			update_fields=['status', 'updated_at'],
			apply_accounting=False,
		)

		with self.assertRaisesRegex(
			services.ClientOrderPaymentError,
			'ya no tiene crédito pendiente',
		):
			services.pay_client_orders(
				client=self.customer,
				orders=[self.order],
				payment_method='cash',
				amount=Decimal('1000.00'),
				request_user=self.user,
			)

		self.customer.refresh_from_db()
		self.assertEqual(self.customer.current_debt, Decimal('1000.00'))
		self.assertFalse(self.order.payments.filter(method='cash').exists())

	def test_branch_without_override_settlement_reduces_corporate_debt(self):
		corporate = Client.objects.create(
			name='Corporativo crédito por liquidar',
			type='corporate',
			credit_limit=Decimal('1000.00'),
			current_debt=Decimal('500.00'),
			can_pay_with_credit=True,
		)
		branch = Client.objects.create(
			name='Sucursal crédito por liquidar',
			type='branch',
			corporate=corporate,
			credit_override_enabled=False,
		)
		order = Order.objects.create(
			client=branch,
			total_amount=Decimal('500.00'),
			type='credito',
		)
		pending_credit = Payment(
			amount=Decimal('500.00'),
			method='pending_credit',
			status='pending',
			client=branch,
			order=order,
			created_by=self.user,
		)
		pending_credit.save(apply_accounting=False)
		CreditTransaction.objects.create(
			client=corporate,
			transaction_type='purchase',
			amount=Decimal('500.00'),
			debt_before=Decimal('0.00'),
			debt_after=Decimal('500.00'),
			credit_limit_before=Decimal('1000.00'),
			credit_limit_after=Decimal('1000.00'),
			reference_order=order,
			reference_payment=pending_credit,
		)

		payment, error = services.settle_credit_order_payment(
			order=order,
			payment_method='cash',
			amount=Decimal('500.00'),
			request_user=self.user,
		)

		self.assertIsNone(error)
		self.assertEqual(payment.client, branch)
		corporate.refresh_from_db()
		branch.refresh_from_db()
		pending_credit.refresh_from_db()
		self.assertEqual(corporate.current_debt, Decimal('0.00'))
		self.assertEqual(branch.current_debt, Decimal('0.00'))
		self.assertEqual(pending_credit.status, 'completed')
		self.assertTrue(
			CreditTransaction.objects.filter(
				client=corporate,
				reference_order=order,
				reference_payment=payment,
				transaction_type='payment',
				amount=Decimal('500.00'),
			).exists()
		)

	def test_branch_settlement_uses_purchase_credit_account_after_override_enabled(self):
		corporate = Client.objects.create(
			name='Corporativo deuda histórica',
			type='corporate',
			credit_limit=Decimal('1000.00'),
			current_debt=Decimal('500.00'),
			can_pay_with_credit=True,
		)
		branch = Client.objects.create(
			name='Sucursal ahora crédito propio',
			type='branch',
			corporate=corporate,
			credit_override_enabled=False,
		)
		order = Order.objects.create(
			client=branch,
			total_amount=Decimal('500.00'),
			type='credito',
		)
		pending_credit = Payment(
			amount=Decimal('500.00'),
			method='pending_credit',
			status='pending',
			client=branch,
			order=order,
			created_by=self.user,
		)
		pending_credit.save(apply_accounting=False)
		CreditTransaction.objects.create(
			client=corporate,
			transaction_type='purchase',
			amount=Decimal('500.00'),
			debt_before=Decimal('0.00'),
			debt_after=Decimal('500.00'),
			credit_limit_before=Decimal('1000.00'),
			credit_limit_after=Decimal('1000.00'),
			reference_order=order,
			reference_payment=pending_credit,
		)
		branch.credit_override_enabled = True
		branch.credit_limit = Decimal('800.00')
		branch.current_debt = Decimal('0.00')
		branch.save(update_fields=[
			'credit_override_enabled',
			'credit_limit',
			'current_debt',
			'updated_at',
		])

		payment, error = services.settle_credit_order_payment(
			order=order,
			payment_method='cash',
			amount=Decimal('500.00'),
			request_user=self.user,
		)

		self.assertIsNone(error)
		self.assertEqual(payment.client, branch)
		corporate.refresh_from_db()
		branch.refresh_from_db()
		pending_credit.refresh_from_db()
		self.assertEqual(corporate.current_debt, Decimal('0.00'))
		self.assertEqual(branch.current_debt, Decimal('0.00'))
		self.assertEqual(pending_credit.status, 'completed')
		self.assertTrue(
			CreditTransaction.objects.filter(
				client=corporate,
				reference_order=order,
				reference_payment=payment,
				transaction_type='payment',
				amount=Decimal('500.00'),
			).exists()
		)

class CreditOrderRegistrationRuleTests(FastTenantTestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username='credit-registration-user',
			password='testpass123',
		)

	def test_branch_without_credit_override_resolves_corporate_credit_account(self):
		corporate = Client.objects.create(
			name='Corporativo cuenta crédito',
			type='corporate',
		)
		branch = Client.objects.create(
			name='Sucursal hereda cuenta crédito',
			type='branch',
			corporate=corporate,
			credit_override_enabled=False,
		)

		self.assertEqual(branch.get_credit_account(), corporate)

	def test_branch_with_credit_override_resolves_own_credit_account(self):
		corporate = Client.objects.create(
			name='Corporativo no usado',
			type='corporate',
		)
		branch = Client.objects.create(
			name='Sucursal crédito propio',
			type='branch',
			corporate=corporate,
			credit_override_enabled=True,
		)

		self.assertEqual(branch.get_credit_account(), branch)

	def test_branch_credit_order_without_override_charges_corporate_credit(self):
		corporate = Client.objects.create(
			name='Corporativo crédito compartido',
			type='corporate',
			credit_limit=Decimal('1000.00'),
			current_debt=Decimal('0.00'),
			can_pay_with_credit=True,
		)
		branch = Client.objects.create(
			name='Sucursal crédito heredado',
			type='branch',
			corporate=corporate,
			credit_limit=Decimal('0.00'),
			current_debt=Decimal('0.00'),
			can_pay_with_credit=False,
			credit_override_enabled=False,
		)
		order = Order.objects.create(
			client=branch,
			total_amount=Decimal('500.00'),
			type='credito',
		)

		response, status_code = services.process_payment_request(
			order=order,
			data=PaymentRequestData(),
			request_user=self.user,
		)

		self.assertEqual(status_code, 200)
		self.assertTrue(response['success'])
		corporate.refresh_from_db()
		branch.refresh_from_db()
		self.assertEqual(corporate.current_debt, Decimal('500.00'))
		self.assertEqual(branch.current_debt, Decimal('0.00'))
		self.assertEqual(corporate.get_available_credit(), Decimal('500.00'))
		self.assertTrue(
			CreditTransaction.objects.filter(
				client=corporate,
				reference_order=order,
				transaction_type='purchase',
				amount=Decimal('500.00'),
			).exists()
		)

	def test_branch_credit_order_without_override_uses_corporate_limit(self):
		corporate = Client.objects.create(
			name='Corporativo límite usado',
			type='corporate',
			credit_limit=Decimal('1000.00'),
			current_debt=Decimal('800.00'),
			can_pay_with_credit=True,
		)
		branch = Client.objects.create(
			name='Sucursal límite heredado',
			type='branch',
			corporate=corporate,
			credit_limit=Decimal('1000.00'),
			current_debt=Decimal('0.00'),
			can_pay_with_credit=True,
			credit_override_enabled=False,
		)
		order = Order.objects.create(
			client=branch,
			total_amount=Decimal('250.00'),
			type='credito',
		)

		response, status_code = services.process_payment_request(
			order=order,
			data=PaymentRequestData(),
			request_user=self.user,
		)

		self.assertEqual(status_code, 400)
		self.assertIn('excede el límite de crédito', response['error'])
		corporate.refresh_from_db()
		branch.refresh_from_db()
		self.assertEqual(corporate.current_debt, Decimal('800.00'))
		self.assertEqual(branch.current_debt, Decimal('0.00'))
		self.assertFalse(order.payments.exists())

	def test_branch_credit_order_with_override_charges_branch_credit(self):
		corporate = Client.objects.create(
			name='Corporativo crédito separado',
			type='corporate',
			credit_limit=Decimal('1000.00'),
			current_debt=Decimal('200.00'),
			can_pay_with_credit=True,
		)
		branch = Client.objects.create(
			name='Sucursal crédito propio',
			type='branch',
			corporate=corporate,
			credit_limit=Decimal('600.00'),
			current_debt=Decimal('0.00'),
			can_pay_with_credit=True,
			credit_override_enabled=True,
		)
		order = Order.objects.create(
			client=branch,
			total_amount=Decimal('500.00'),
			type='credito',
		)

		response, status_code = services.process_payment_request(
			order=order,
			data=PaymentRequestData(),
			request_user=self.user,
		)

		self.assertEqual(status_code, 200)
		self.assertTrue(response['success'])
		corporate.refresh_from_db()
		branch.refresh_from_db()
		self.assertEqual(corporate.current_debt, Decimal('200.00'))
		self.assertEqual(branch.current_debt, Decimal('500.00'))

	def test_credit_order_emergency_stop_blocks_even_when_limit_is_available(self):
		customer = Client.objects.create(
			name='Cliente crédito bloqueado con límite',
			type='corporate',
			balance=Decimal('30.00'),
			credit_limit=Decimal('200.00'),
			current_debt=Decimal('0.00'),
			can_pay_with_credit=False,
		)
		order = Order.objects.create(
			client=customer,
			total_amount=Decimal('100.00'),
			type='credito',
		)

		response, status_code = services.process_payment_request(
			order=order,
			data=PaymentRequestData(),
			request_user=self.user,
		)

		self.assertEqual(status_code, 400)
		self.assertEqual(response['error'], 'Cliente no puede pagar con credito')
		customer.refresh_from_db()
		self.assertEqual(customer.balance, Decimal('30.00'))
		self.assertEqual(customer.current_debt, Decimal('0.00'))
		self.assertFalse(order.payments.exists())

	def test_overdue_credit_is_reported_but_does_not_block_credit_order(self):
		customer = Client.objects.create(
			name='Cliente vencido con límite disponible',
			type='corporate',
			credit_limit=Decimal('500.00'),
			current_debt=Decimal('0.00'),
			can_pay_with_credit=True,
		)
		ClientCreditConfig.objects.create(
			client=customer,
			payment_term_type='monthly_cutoff',
			cutoff_day='last_day',
		)
		overdue_order = Order.objects.create(
			client=customer,
			total_amount=Decimal('100.00'),
			type='credito',
		)
		balance_service.add_debt(
			client=customer,
			amount=Decimal('100.00'),
			transaction_type='purchase',
			reference_order=overdue_order,
		)
		Order.objects.filter(pk=overdue_order.pk).update(
			order_date=timezone.now() - timedelta(days=60),
		)
		self.assertTrue(client_has_overdue_credit(customer))
		new_order = Order.objects.create(
			client=customer,
			total_amount=Decimal('50.00'),
			type='credito',
		)

		response, status_code = services.process_payment_request(
			order=new_order,
			data=PaymentRequestData(),
			request_user=self.user,
		)

		self.assertEqual(status_code, 200)
		self.assertTrue(response['success'])
		customer.refresh_from_db()
		self.assertEqual(customer.current_debt, Decimal('150.00'))
		self.assertTrue(
			new_order.payments.filter(
				method='pending_credit',
				status='pending',
				amount=Decimal('50.00'),
			).exists()
		)

	def test_branch_without_override_overdue_lookup_uses_corporate_credit_config(self):
		corporate = Client.objects.create(
			name='Corporativo vencimiento heredado',
			type='corporate',
			credit_limit=Decimal('1000.00'),
			can_pay_with_credit=True,
		)
		ClientCreditConfig.objects.create(
			client=corporate,
			payment_term_type='monthly_cutoff',
			cutoff_day='last_day',
		)
		branch = Client.objects.create(
			name='Sucursal vencimiento heredado',
			type='branch',
			corporate=corporate,
			credit_override_enabled=False,
		)
		order = Order.objects.create(
			client=branch,
			total_amount=Decimal('100.00'),
			type='credito',
		)
		balance_service.add_debt(
			client=branch,
			amount=Decimal('100.00'),
			transaction_type='purchase',
			reference_order=order,
		)
		Order.objects.filter(pk=order.pk).update(
			order_date=timezone.now() - timedelta(days=60),
		)

		self.assertTrue(client_has_overdue_credit(branch))

	def test_credit_order_fails_when_remaining_amount_exceeds_available_limit(self):
		customer = Client.objects.create(
			name='Cliente sin límite suficiente',
			type='corporate',
			balance=Decimal('10.00'),
			credit_limit=Decimal('100.00'),
			current_debt=Decimal('80.00'),
			can_pay_with_credit=True,
		)
		order = Order.objects.create(
			client=customer,
			total_amount=Decimal('50.00'),
			type='credito',
		)

		response, status_code = services.process_payment_request(
			order=order,
			data=PaymentRequestData(),
			request_user=self.user,
		)

		self.assertEqual(status_code, 400)
		self.assertIn('excede el límite de crédito', response['error'])
		customer.refresh_from_db()
		self.assertEqual(customer.balance, Decimal('10.00'))
		self.assertEqual(customer.current_debt, Decimal('80.00'))
		self.assertFalse(order.payments.exists())

	def test_mixed_payment_rows_register_only_credit_portion_as_debt(self):
		customer = Client.objects.create(
			name='Cliente pago mixto con crédito',
			type='corporate',
			balance=Decimal('20.00'),
			credit_limit=Decimal('200.00'),
			current_debt=Decimal('0.00'),
			can_pay_with_credit=True,
		)
		order = Order.objects.create(
			client=customer,
			total_amount=Decimal('100.00'),
			type='contado',
		)

		response, status_code = services.process_payment_request(
			order=order,
			data=PaymentRequestData(
				order_type='contado',
				payments_data=[
					{'amount': '20.00', 'payment_method': 'balance'},
					{'amount': '30.00', 'payment_method': 'cash'},
					{'amount': '50.00', 'payment_method': 'credit'},
				],
			),
			request_user=self.user,
		)

		self.assertEqual(status_code, 200)
		self.assertTrue(response['success'])
		order.refresh_from_db()
		customer.refresh_from_db()
		self.assertEqual(order.type, 'credito')
		self.assertEqual(order.status, OrderStatus.COMPLETED.value)
		self.assertEqual(customer.balance, Decimal('0.00'))
		self.assertEqual(customer.current_debt, Decimal('50.00'))
		self.assertTrue(
			order.payments.filter(
				method='balance',
				status='completed',
				amount=Decimal('20.00'),
			).exists()
		)
		self.assertTrue(
			order.payments.filter(
				method='cash',
				status='completed',
				amount=Decimal('30.00'),
			).exists()
		)
		pending_credit = order.payments.get(method='pending_credit')
		self.assertEqual(pending_credit.status, 'pending')
		self.assertEqual(pending_credit.amount, Decimal('50.00'))
		self.assertEqual(order.total_paid, Decimal('50.00'))
		self.assertTrue(
			CreditTransaction.objects.filter(
				client=customer,
				transaction_type='purchase',
				amount=Decimal('50.00'),
				reference_order=order,
				reference_payment=pending_credit,
			).exists()
		)

	def test_mixed_payment_rows_reject_credit_portion_over_available_limit_atomically(self):
		customer = Client.objects.create(
			name='Cliente pago mixto sin crédito suficiente',
			type='corporate',
			balance=Decimal('20.00'),
			credit_limit=Decimal('40.00'),
			current_debt=Decimal('0.00'),
			can_pay_with_credit=True,
		)
		order = Order.objects.create(
			client=customer,
			total_amount=Decimal('100.00'),
			type='contado',
		)

		response, status_code = services.process_payment_request(
			order=order,
			data=PaymentRequestData(
				payments_data=[
					{'amount': '20.00', 'payment_method': 'balance'},
					{'amount': '30.00', 'payment_method': 'cash'},
					{'amount': '50.00', 'payment_method': 'credit'},
				],
			),
			request_user=self.user,
		)

		self.assertEqual(status_code, 400)
		self.assertIn('excede el límite de crédito', response['error'])
		order.refresh_from_db()
		customer.refresh_from_db()
		self.assertEqual(order.type, 'contado')
		self.assertEqual(order.status, OrderStatus.PENDING.value)
		self.assertEqual(customer.balance, Decimal('20.00'))
		self.assertEqual(customer.current_debt, Decimal('0.00'))
		self.assertFalse(order.payments.exists())
