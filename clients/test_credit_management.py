from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from clients.models import Client, ClientCreditConfig
from clients.services import balance_service
from clients.services.client_service import (
    ClientUpdateData,
    initialize_branch_credit_from_corporate,
    sync_inherited_branch_credit_from_corporate,
    update_client,
)
from clients.services.pending_payment_service import client_has_overdue_credit
from orders.models import Order
from tenant_client.test_utils import FastTenantTestCase


User = get_user_model()


class ClientCreditAvailabilityTests(SimpleTestCase):
    def test_disabled_credit_cannot_be_used_with_available_limit(self) -> None:
        client = Client(
            can_pay_with_credit=False,
            credit_limit=Decimal('1000.00'),
            current_debt=Decimal('100.00'),
        )

        self.assertFalse(client.can_use_credit_for_payment())

    def test_fully_used_credit_limit_cannot_be_used(self) -> None:
        client = Client(
            can_pay_with_credit=True,
            credit_limit=Decimal('1000.00'),
            current_debt=Decimal('1000.00'),
        )

        self.assertFalse(client.can_use_credit_for_payment())


class CreditConfigurationValidationTests(FastTenantTestCase):
    def test_credit_can_be_disabled_with_existing_debt_and_limit(self) -> None:
        client = Client.objects.create(
            name='Cliente con paro de emergencia',
            type='corporate',
            credit_limit=Decimal('500.00'),
            current_debt=Decimal('100.00'),
            can_pay_with_credit=False,
        )

        client.full_clean()

        self.assertFalse(client.can_pay_with_credit)

    def test_invoice_due_requires_billing(self) -> None:
        client = Client.objects.create(
            name='Cliente sin facturación',
            type='corporate',
            requires_billing=False,
        )
        config = ClientCreditConfig(
            client=client,
            payment_term_type='invoice_due',
        )

        with self.assertRaises(ValidationError) as context:
            config.full_clean()

        self.assertIn('payment_term_type', context.exception.message_dict)

    def test_billing_cannot_be_disabled_for_invoice_due_terms(self) -> None:
        client = Client.objects.create(
            name='Cliente facturado',
            type='corporate',
            requires_billing=True,
        )
        ClientCreditConfig.objects.create(
            client=client,
            payment_term_type='invoice_due',
        )
        client.requires_billing = False

        with self.assertRaises(ValidationError) as context:
            client.full_clean()

        self.assertIn('requires_billing', context.exception.message_dict)


class BranchCreditServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='credit-service-user')
        self.corporate = Client.objects.create(
            name='Corporativo crédito',
            type='corporate',
            requires_billing=True,
            credit_limit=Decimal('750.00'),
            can_pay_with_credit=False,
        )
        ClientCreditConfig.objects.create(
            client=self.corporate,
            payment_term_type='invoice_due',
            max_payment_days=30,
        )

    def test_initialization_copies_policy_without_copying_ledger(self) -> None:
        branch = Client.objects.create(
            name='Sucursal nueva',
            type='branch',
            corporate=self.corporate,
            balance=Decimal('25.00'),
            current_debt=Decimal('40.00'),
            credit_limit=Decimal('10.00'),
            can_pay_with_credit=True,
        )

        initialize_branch_credit_from_corporate(branch)

        branch.refresh_from_db()
        self.assertEqual(branch.credit_limit, Decimal('750.00'))
        self.assertFalse(branch.can_pay_with_credit)
        self.assertTrue(branch.requires_billing)
        self.assertEqual(branch.balance, Decimal('25.00'))
        self.assertEqual(branch.current_debt, Decimal('40.00'))
        self.assertEqual(branch.credit_config.payment_term_type, 'invoice_due')
        self.assertEqual(branch.credit_config.max_payment_days, 30)

    def test_sync_updates_only_branches_without_override(self) -> None:
        inherited_branch = Client.objects.create(
            name='Sucursal heredada',
            type='branch',
            corporate=self.corporate,
            credit_limit=Decimal('10.00'),
            can_pay_with_credit=True,
        )
        override_branch = Client.objects.create(
            name='Sucursal propia',
            type='branch',
            corporate=self.corporate,
            credit_override_enabled=True,
            credit_limit=Decimal('55.00'),
            can_pay_with_credit=True,
        )

        changed_count = sync_inherited_branch_credit_from_corporate(self.corporate)

        inherited_branch.refresh_from_db()
        override_branch.refresh_from_db()
        self.assertEqual(changed_count, 1)
        self.assertEqual(inherited_branch.credit_limit, Decimal('750.00'))
        self.assertFalse(inherited_branch.can_pay_with_credit)
        self.assertEqual(override_branch.credit_limit, Decimal('55.00'))
        self.assertTrue(override_branch.can_pay_with_credit)

    def test_inherited_branch_rejects_direct_credit_policy_update(self) -> None:
        branch = Client.objects.create(
            name='Sucursal administrada',
            type='branch',
            corporate=self.corporate,
            credit_limit=Decimal('750.00'),
        )

        with self.assertRaisesRegex(ValueError, 'corporativo'):
            update_client(
                branch,
                ClientUpdateData(credit_limit=Decimal('900.00')),
                self.user,
            )

        branch.refresh_from_db()
        self.assertEqual(branch.credit_limit, Decimal('750.00'))

    def test_override_branch_accepts_direct_credit_policy_update(self) -> None:
        branch = Client.objects.create(
            name='Sucursal autónoma',
            type='branch',
            corporate=self.corporate,
            credit_override_enabled=True,
            credit_limit=Decimal('100.00'),
        )

        update_client(
            branch,
            ClientUpdateData(credit_limit=Decimal('500.00')),
            self.user,
        )

        branch.refresh_from_db()
        self.assertEqual(branch.credit_limit, Decimal('500.00'))


class CreditSaleEnforcementTests(FastTenantTestCase):
    def test_emergency_credit_stop_blocks_new_credit_sale(self) -> None:
        client = Client.objects.create(
            name='Cliente bloqueado',
            type='corporate',
            credit_limit=Decimal('500.00'),
            current_debt=Decimal('0.00'),
            can_pay_with_credit=False,
        )

        with self.assertRaisesRegex(ValueError, 'Cliente no puede pagar con credito'):
            balance_service.add_debt(
                client=client,
                amount=Decimal('50.00'),
                transaction_type='purchase',
            )

        client.refresh_from_db()
        self.assertEqual(client.current_debt, Decimal('0.00'))

    def test_credit_sale_cannot_exceed_hard_limit(self) -> None:
        client = Client.objects.create(
            name='Cliente al límite',
            type='corporate',
            credit_limit=Decimal('100.00'),
            current_debt=Decimal('90.00'),
            can_pay_with_credit=True,
        )

        with self.assertRaisesRegex(ValueError, 'excede el límite de crédito'):
            balance_service.add_debt(
                client=client,
                amount=Decimal('20.00'),
                transaction_type='purchase',
            )

        client.refresh_from_db()
        self.assertEqual(client.current_debt, Decimal('90.00'))

    def test_overdue_credit_does_not_block_new_credit_sale_when_limit_available(self) -> None:
        client = Client.objects.create(
            name='Cliente vencido',
            type='corporate',
            credit_limit=Decimal('500.00'),
            can_pay_with_credit=True,
        )
        ClientCreditConfig.objects.create(
            client=client,
            payment_term_type='monthly_cutoff',
            cutoff_day='last_day',
        )
        overdue_order = Order.objects.create(
            client=client,
            total_amount=Decimal('100.00'),
            type='credito',
        )
        balance_service.add_debt(
            client=client,
            amount=Decimal('100.00'),
            transaction_type='purchase',
            reference_order=overdue_order,
        )
        Order.objects.filter(pk=overdue_order.pk).update(
            order_date=timezone.now() - timedelta(days=60),
        )
        self.assertTrue(client_has_overdue_credit(client))
        new_order = Order.objects.create(
            client=client,
            total_amount=Decimal('50.00'),
            type='credito',
        )

        balance_service.add_debt(
            client=client,
            amount=Decimal('50.00'),
            transaction_type='purchase',
            reference_order=new_order,
        )

        client.refresh_from_db()
        self.assertEqual(client.current_debt, Decimal('150.00'))
