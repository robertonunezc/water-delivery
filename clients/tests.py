from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date, timedelta
from .models import (
    Client, BillingData, Address, BalanceTransaction, CreditTransaction,
    Contact, ClientBillingFrecuency, ClientCreditConfig
)

User = get_user_model()


class ClientBillingInheritanceTestCase(TestCase):
    """Test cases for corporate/branch billing data inheritance"""

    def setUp(self):
        """Set up test data for billing inheritance tests"""
        # Create a corporate client
        self.corporate = Client.objects.create(
            name="Corporate Client",
            type="corporate",
            active=True
        )

        # Create billing data for corporate
        self.corporate_billing_data = BillingData.objects.create(
            client=self.corporate,
            rfc="CORP123456ABC",
            razon_social="Corporativo SA de CV"
        )

        # Create billing address for corporate
        self.corporate_billing_address = Address.objects.create(
            client=self.corporate,
            type="billing",
            street="Av. Corporativa 100",
            municipality="Querétaro",
            state="Querétaro",
            zip_code="76000",
            country="México",
            active=True
        )

        # Create branch client
        self.branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True
        )

    def test_branch_inherits_billing_data_from_corporate(self):
        """Test that branch without own billing data inherits from corporate"""
        effective_data = self.branch.get_effective_billing_data()
        self.assertIsNotNone(effective_data)
        self.assertEqual(effective_data.rfc, "CORP123456ABC")
        self.assertEqual(effective_data.razon_social, "Corporativo SA de CV")

    def test_branch_inherits_billing_address_from_corporate(self):
        """Test that branch without own billing address inherits from corporate"""
        effective_address = self.branch.get_effective_billing_address()
        self.assertIsNotNone(effective_address)
        self.assertEqual(effective_address.street, "Av. Corporativa 100")
        self.assertEqual(effective_address.type, "billing")

    def test_branch_uses_own_billing_data_when_available(self):
        """Test that branch uses its own billing data when it has one"""
        # Create branch-specific billing data
        branch_billing_data = BillingData.objects.create(
            client=self.branch,
            rfc="BRANCH123456XYZ",
            razon_social="Sucursal SA de CV"
        )

        effective_data = self.branch.get_effective_billing_data()
        self.assertEqual(effective_data.rfc, "BRANCH123456XYZ")
        self.assertEqual(effective_data.razon_social, "Sucursal SA de CV")

    def test_branch_uses_own_billing_address_when_available(self):
        """Test that branch uses its own billing address when it has one"""
        # Create branch-specific billing address
        branch_billing_address = Address.objects.create(
            client=self.branch,
            type="billing",
            street="Av. Sucursal 200",
            municipality="Querétaro",
            state="Querétaro",
            zip_code="76100",
            country="México",
            active=True
        )

        effective_address = self.branch.get_effective_billing_address()
        self.assertEqual(effective_address.street, "Av. Sucursal 200")

    def test_corporate_returns_own_billing_data(self):
        """Test that corporate client returns its own billing data"""
        effective_data = self.corporate.get_effective_billing_data()
        self.assertEqual(effective_data.rfc, "CORP123456ABC")

    def test_corporate_without_billing_data_returns_none(self):
        """Test that corporate without billing data returns None"""
        corporate_no_billing = Client.objects.create(
            name="Corporate No Billing",
            type="corporate",
            active=True
        )
        self.assertIsNone(corporate_no_billing.get_effective_billing_data())

    def test_branch_without_corporate_returns_none(self):
        """Test that branch without corporate parent and no own data returns None"""
        # This should not happen in practice due to validation, but test the method
        branch_no_corporate = Client.objects.create(
            name="Orphan Branch",
            type="branch",
            active=True
        )
        self.assertIsNone(branch_no_corporate.get_effective_billing_data())

    def test_has_complete_billing_setup_with_both_data_and_address(self):
        """Test has_complete_billing_setup returns True when both data and address exist"""
        self.assertTrue(self.corporate.has_complete_billing_setup())

    def test_has_complete_billing_setup_inherited(self):
        """Test has_complete_billing_setup returns True for branch inheriting from corporate"""
        self.assertTrue(self.branch.has_complete_billing_setup())

    def test_has_complete_billing_setup_without_data(self):
        """Test has_complete_billing_setup returns False without billing data"""
        corporate_no_data = Client.objects.create(
            name="Corporate No Data",
            type="corporate",
            active=True
        )
        Address.objects.create(
            client=corporate_no_data,
            type="billing",
            street="Test Street",
            municipality="Querétaro",
            active=True
        )
        self.assertFalse(corporate_no_data.has_complete_billing_setup())

    def test_has_complete_billing_setup_without_address(self):
        """Test has_complete_billing_setup returns False without billing address"""
        corporate_no_address = Client.objects.create(
            name="Corporate No Address",
            type="corporate",
            active=True
        )
        BillingData.objects.create(
            client=corporate_no_address,
            rfc="TEST123456ABC",
            razon_social="Test SA"
        )
        self.assertFalse(corporate_no_address.has_complete_billing_setup())

    def test_get_billing_source_returns_own(self):
        """Test get_billing_source returns 'own' when client has complete own billing"""
        self.assertEqual(self.corporate.get_billing_source(), 'own')

    def test_get_billing_source_returns_corporate_for_branch(self):
        """Test get_billing_source returns 'corporate' for branch inheriting"""
        self.assertEqual(self.branch.get_billing_source(), 'corporate')

    def test_get_billing_source_returns_own_for_branch_with_own_data(self):
        """Test get_billing_source returns 'own' for branch with complete own billing"""
        BillingData.objects.create(
            client=self.branch,
            rfc="BRANCH123456XYZ",
            razon_social="Sucursal SA de CV"
        )
        Address.objects.create(
            client=self.branch,
            type="billing",
            street="Branch Street",
            municipality="Querétaro",
            active=True
        )
        self.assertEqual(self.branch.get_billing_source(), 'own')

    def test_get_billing_source_returns_none(self):
        """Test get_billing_source returns 'none' when no billing data available"""
        corporate_no_billing = Client.objects.create(
            name="Corporate No Billing",
            type="corporate",
            active=True
        )
        self.assertEqual(corporate_no_billing.get_billing_source(), 'none')


class ClientValidationTestCase(TestCase):
    """Test cases for Client model validation"""

    def setUp(self):
        """Set up test data for validation tests"""
        self.corporate = Client.objects.create(
            name="Corporate Client",
            type="corporate",
            active=True
        )

    def test_branch_requires_corporate(self):
        """Test that branch type requires a corporate parent"""
        branch = Client(
            name="Branch Without Corporate",
            type="branch",
            active=True
        )
        with self.assertRaises(ValidationError) as context:
            branch.clean()
        self.assertIn('corporate', context.exception.message_dict)

    def test_corporate_cannot_have_corporate_parent(self):
        """Test that corporate cannot have another corporate as parent"""
        another_corporate = Client.objects.create(
            name="Another Corporate",
            type="corporate",
            active=True
        )
        self.corporate.corporate = another_corporate
        with self.assertRaises(ValidationError) as context:
            self.corporate.clean()
        self.assertIn('corporate', context.exception.message_dict)

    def test_branch_requires_billing_without_corporate_billing_fails(self):
        """Test that branch cannot require billing if corporate lacks billing setup"""
        branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True
        )
        branch.requires_billing = True

        with self.assertRaises(ValidationError) as context:
            branch.clean()
        self.assertIn('requires_billing', context.exception.message_dict)

    def test_branch_requires_billing_with_corporate_billing_succeeds(self):
        """Test that branch can require billing if corporate has complete billing setup"""
        # Add complete billing to corporate
        BillingData.objects.create(
            client=self.corporate,
            rfc="CORP123456ABC",
            razon_social="Corporativo SA de CV"
        )
        Address.objects.create(
            client=self.corporate,
            type="billing",
            street="Corporate Street",
            municipality="Querétaro",
            active=True
        )

        branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            requires_billing=True,
            active=True
        )

        # Add shipping address (required for branches)
        Address.objects.create(
            client=branch,
            type="shipping",
            street="Branch Shipping Street",
            municipality="Querétaro",
            active=True
        )

        # Should not raise ValidationError
        try:
            branch.clean()
        except ValidationError:
            self.fail("Branch with corporate billing should pass validation")

    def test_branch_requires_billing_with_own_billing_succeeds(self):
        """Test that branch can require billing if it has its own complete billing setup"""
        branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True
        )

        # Add complete billing to branch
        BillingData.objects.create(
            client=branch,
            rfc="BRANCH123456XYZ",
            razon_social="Sucursal SA de CV"
        )
        Address.objects.create(
            client=branch,
            type="billing",
            street="Branch Street",
            municipality="Querétaro",
            active=True
        )

        # Add shipping address (required for branches)
        Address.objects.create(
            client=branch,
            type="shipping",
            street="Branch Shipping Street",
            municipality="Querétaro",
            active=True
        )

        branch.requires_billing = True

        # Should not raise ValidationError
        try:
            branch.clean()
        except ValidationError:
            self.fail("Branch with own billing should pass validation")

    def test_corporate_can_require_billing_with_complete_setup(self):
        """Test that corporate can require billing if it has complete billing setup"""
        BillingData.objects.create(
            client=self.corporate,
            rfc="CORP123456ABC",
            razon_social="Corporativo SA de CV"
        )
        Address.objects.create(
            client=self.corporate,
            type="billing",
            street="Corporate Street",
            municipality="Querétaro",
            active=True
        )

        self.corporate.requires_billing = True

        # Should not raise ValidationError
        try:
            self.corporate.clean()
        except ValidationError:
            self.fail("Corporate with billing setup should pass validation")

    def test_cannot_disable_credit_and_require_note(self):
        """Test that cannot disable credit payment and require note at the same time"""
        client = Client.objects.create(
            name="Test Client",
            type="corporate",
            can_pay_with_credit=False,
            requires_note_for_credit=True,
            active=True
        )

        with self.assertRaises(ValidationError) as context:
            client.clean()
        self.assertIn('can_pay_with_credit', context.exception.message_dict)
        self.assertIn('requires_note_for_credit', context.exception.message_dict)

    def test_cannot_disable_credit_with_existing_debt(self):
        """Test that cannot disable credit payment if client has existing debt"""
        client = Client.objects.create(
            name="Test Client",
            type="corporate",
            current_debt=Decimal('100.00'),
            credit_limit=Decimal('500.00'),
            active=True
        )

        client.can_pay_with_credit = False

        with self.assertRaises(ValidationError) as context:
            client.clean()
        self.assertIn('can_pay_with_credit', context.exception.message_dict)

    def test_debt_cannot_exceed_credit_limit(self):
        """Test that current debt cannot exceed credit limit"""
        client = Client.objects.create(
            name="Test Client",
            type="corporate",
            current_debt=Decimal('600.00'),
            credit_limit=Decimal('500.00'),
            active=True
        )

        with self.assertRaises(ValidationError) as context:
            client.clean()
        self.assertIn('current_debt', context.exception.message_dict)

    def test_cannot_set_credit_limit_without_enabling_credit(self):
        """Test that cannot set credit limit without enabling credit payment"""
        client = Client.objects.create(
            name="Test Client",
            type="corporate",
            can_pay_with_credit=False,
            credit_limit=Decimal('500.00'),
            active=True
        )

        with self.assertRaises(ValidationError) as context:
            client.clean()
        self.assertIn('can_pay_with_credit', context.exception.message_dict)

    def test_create_new_branch_with_requires_billing_succeeds(self):
        """Test that creating a new branch with requires_billing=True works (validation deferred)"""
        # This simulates what happens in the admin when creating a new client
        branch = Client(
            name="New Branch",
            type="branch",
            corporate=self.corporate,
            requires_billing=True,
            active=True
        )

        # Should not raise ValidationError on new instance (no pk yet)
        try:
            branch.clean()
        except ValidationError as e:
            # Should only complain about missing corporate, not billing setup
            if 'requires_billing' in e.message_dict:
                self.fail("Should not validate billing setup before instance is saved")

    def test_create_new_corporate_succeeds(self):
        """Test that creating a new corporate client works without issues"""
        corporate = Client(
            name="New Corporate",
            type="corporate",
            active=True
        )

        # Should not raise ValidationError
        try:
            corporate.clean()
        except ValidationError:
            self.fail("Creating new corporate should not raise validation errors")

    def test_update_branch_requires_billing_validates(self):
        """Test that updating an existing branch to require billing validates correctly"""
        # Create and save a branch first
        branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True
        )

        # Now try to update it to require billing without proper setup
        branch.requires_billing = True

        # Should raise ValidationError because branch is saved (has pk) and lacks billing
        with self.assertRaises(ValidationError) as context:
            branch.clean()
        self.assertIn('requires_billing', context.exception.message_dict)

    def test_branch_has_shipping_address(self):
        """Test has_shipping_address method returns correct value"""
        branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True
        )

        # Initially no shipping address
        self.assertFalse(branch.has_shipping_address())

        # Add shipping address
        Address.objects.create(
            client=branch,
            type="shipping",
            street="Branch Street",
            municipality="Querétaro",
            active=True
        )

        # Now should have shipping address
        self.assertTrue(branch.has_shipping_address())

    def test_branch_can_receive_orders_without_shipping_address(self):
        """Test that branch cannot receive orders without shipping address"""
        branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True
        )

        can_receive, error_msg = branch.can_receive_orders()
        self.assertFalse(can_receive)
        self.assertIn('domicilio de envío', error_msg.lower())

    def test_branch_can_receive_orders_with_shipping_address(self):
        """Test that branch can receive orders with shipping address"""
        branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True
        )

        # Add shipping address
        Address.objects.create(
            client=branch,
            type="shipping",
            street="Branch Street",
            municipality="Querétaro",
            active=True
        )

        can_receive, error_msg = branch.can_receive_orders()
        self.assertTrue(can_receive)
        self.assertEqual(error_msg, '')

    def test_inactive_client_cannot_receive_orders(self):
        """Test that inactive client cannot receive orders"""
        client = Client.objects.create(
            name="Inactive Client",
            type="corporate",
            active=False
        )

        can_receive, error_msg = client.can_receive_orders()
        self.assertFalse(can_receive)
        self.assertIn('activo', error_msg.lower())


class ClientBalanceManagementTestCase(TestCase):
    """Test cases for client balance management"""

    def setUp(self):
        """Set up test data for balance tests"""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client = Client.objects.create(
            name="Test Client",
            type="corporate",
            balance=Decimal('1000.00'),
            active=True
        )

    def test_add_balance_increases_balance(self):
        """Test that add_balance increases client balance"""
        from clients.services import balance_service
        initial_balance = self.client.balance
        amount = Decimal('500.00')

        transaction = balance_service.add_balance(
            client=self.client,
            amount=amount,
            transaction_type='deposit',
            user=self.user,
            notes="Test deposit"
        )

        self.client.refresh_from_db()
        self.assertEqual(self.client.balance, initial_balance + amount)

    def test_add_balance_creates_transaction_record(self):
        """Test that add_balance creates a BalanceTransaction record"""
        from clients.services import balance_service
        amount = Decimal('500.00')

        balance_service.add_balance(
            client=self.client,
            amount=amount,
            transaction_type='deposit',
            user=self.user,
            notes="Test deposit"
        )

        transaction = BalanceTransaction.objects.filter(client=self.client).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.amount, amount)
        self.assertEqual(transaction.transaction_type, 'deposit')
        self.assertEqual(transaction.created_by, self.user)

    def test_add_balance_with_negative_amount_raises_error(self):
        """Test that add_balance raises error with negative amount"""
        from clients.services import balance_service
        with self.assertRaises(ValueError):
            balance_service.add_balance(
                client=self.client,
                amount=Decimal('-100.00'),
                transaction_type='deposit',
                user=self.user
            )

    def test_deduct_balance_decreases_balance(self):
        """Test that deduct_balance decreases client balance"""
        from clients.services import balance_service
        initial_balance = self.client.balance
        amount = Decimal('300.00')

        result = balance_service.deduct_balance(
            client=self.client,
            amount=amount,
            transaction_type='payment',
            user=self.user,
            notes="Test payment"
        )

        self.assertIsNotNone(result)
        self.client.refresh_from_db()
        self.assertEqual(self.client.balance, initial_balance - amount)

    def test_deduct_balance_with_insufficient_funds_fails(self):
        """Test that deduct_balance fails with insufficient balance"""
        from clients.services import balance_service
        amount = Decimal('2000.00')  # More than current balance

        result = balance_service.deduct_balance(
            client=self.client,
            amount=amount,
            transaction_type='payment',
            user=self.user
        )

        self.assertIsNone(result)
        self.client.refresh_from_db()
        self.assertEqual(self.client.balance, Decimal('1000.00'))  # Unchanged

    def test_deduct_balance_creates_transaction_record(self):
        """Test that deduct_balance creates a BalanceTransaction record"""
        from clients.services import balance_service
        amount = Decimal('200.00')

        balance_service.deduct_balance(
            client=self.client,
            amount=amount,
            transaction_type='payment',
            user=self.user
        )

        transaction = BalanceTransaction.objects.filter(client=self.client).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.amount, amount)
        self.assertEqual(transaction.transaction_type, 'payment')


class ClientCreditManagementTestCase(TestCase):
    """Test cases for client credit management"""

    def setUp(self):
        """Set up test data for credit tests"""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client = Client.objects.create(
            name="Test Client",
            type="corporate",
            credit_limit=Decimal('5000.00'),
            current_debt=Decimal('1000.00'),
            can_pay_with_credit=True,
            active=True
        )

    def test_add_debt_increases_debt(self):
        """Test that add_debt increases current debt"""
        from clients.services import balance_service
        initial_debt = self.client.current_debt
        amount = Decimal('500.00')

        result = balance_service.add_debt(
            client=self.client,
            amount=amount,
            transaction_type='purchase',
            user=self.user,
            notes="Test purchase"
        )

        self.assertIsNotNone(result)
        self.client.refresh_from_db()
        self.assertEqual(self.client.current_debt, initial_debt + amount)

    def test_add_debt_creates_transaction_record(self):
        """Test that add_debt creates a CreditTransaction record"""
        from clients.services import balance_service
        amount = Decimal('500.00')

        balance_service.add_debt(
            client=self.client,
            amount=amount,
            transaction_type='purchase',
            user=self.user
        )

        transaction = CreditTransaction.objects.filter(client=self.client).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.amount, amount)
        self.assertEqual(transaction.transaction_type, 'purchase')

    def test_add_debt_exceeding_limit_with_can_pay_credit_true_succeeds(self):
        """Test that add_debt allows exceeding limit when can_pay_with_credit is True"""
        from clients.services import balance_service
        amount = Decimal('6000.00')  # Exceeds available credit

        result = balance_service.add_debt(
            client=self.client,
            amount=amount,
            transaction_type='purchase',
            user=self.user
        )

        self.assertIsNotNone(result)
        self.client.refresh_from_db()
        self.assertEqual(self.client.current_debt, Decimal('7000.00'))

    def test_add_debt_exceeding_limit_with_can_pay_credit_false_fails(self):
        """Test that add_debt blocks exceeding limit when can_pay_with_credit is False"""
        from clients.services import balance_service
        self.client.can_pay_with_credit = False
        self.client.save()

        amount = Decimal('5000.00')  # Would exceed limit

        result = balance_service.add_debt(
            client=self.client,
            amount=amount,
            transaction_type='purchase',
            user=self.user
        )

        self.assertIsNone(result)
        self.client.refresh_from_db()
        self.assertEqual(self.client.current_debt, Decimal('1000.00'))  # Unchanged

    def test_pay_debt_decreases_debt(self):
        """Test that pay_debt decreases current debt"""
        from clients.services import balance_service
        initial_debt = self.client.current_debt
        amount = Decimal('500.00')

        paid = balance_service.pay_debt(
            client=self.client,
            amount=amount,
            transaction_type='payment',
            user=self.user
        )

        self.assertEqual(paid, amount)
        self.client.refresh_from_db()
        self.assertEqual(self.client.current_debt, initial_debt - amount)

    def test_pay_debt_limited_by_current_debt(self):
        """Test that pay_debt is limited by current debt amount"""
        from clients.services import balance_service
        amount = Decimal('2000.00')  # More than current debt

        paid = balance_service.pay_debt(
            client=self.client,
            amount=amount,
            transaction_type='payment',
            user=self.user
        )

        self.assertEqual(paid, Decimal('1000.00'))  # Only paid existing debt
        self.client.refresh_from_db()
        self.assertEqual(self.client.current_debt, Decimal('0.00'))

    def test_get_available_credit(self):
        """Test get_available_credit returns correct amount"""
        available = self.client.get_available_credit()
        expected = Decimal('4000.00')  # 5000 limit - 1000 debt
        self.assertEqual(available, expected)

    def test_update_credit_limit(self):
        """Test update_credit_limit changes limit and creates transaction"""
        from clients.services import balance_service
        new_limit = Decimal('10000.00')

        balance_service.update_credit_limit(
            client=self.client,
            new_limit=new_limit,
            user=self.user,
            notes="Increasing credit limit"
        )

        self.client.refresh_from_db()
        self.assertEqual(self.client.credit_limit, new_limit)

        transaction = CreditTransaction.objects.filter(
            client=self.client,
            transaction_type='limit_change'
        ).first()
        self.assertIsNotNone(transaction)

    def test_pay_debt_from_balance_success(self):
        """Test pay_debt_from_balance with sufficient balance"""
        from clients.services import balance_service
        self.client.balance = Decimal('500.00')
        self.client.save()

        amount = Decimal('300.00')
        result = balance_service.pay_debt_from_balance(
            client=self.client,
            amount=amount,
            user=self.user
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['amount_paid'], amount)
        self.client.refresh_from_db()
        self.assertEqual(self.client.balance, Decimal('200.00'))
        self.assertEqual(self.client.current_debt, Decimal('700.00'))

    def test_pay_debt_from_balance_insufficient_balance(self):
        """Test pay_debt_from_balance fails with insufficient balance"""
        from clients.services import balance_service
        self.client.balance = Decimal('100.00')
        self.client.save()

        amount = Decimal('300.00')
        result = balance_service.pay_debt_from_balance(
            client=self.client,
            amount=amount,
            user=self.user
        )

        self.assertFalse(result['success'])
        self.assertIn('error', result)


class ClientPaymentProcessingTestCase(TestCase):
    """Test cases for client payment processing"""

    def setUp(self):
        """Set up test data for payment tests"""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client = Client.objects.create(
            name="Test Client",
            type="corporate",
            balance=Decimal('500.00'),
            credit_limit=Decimal('2000.00'),
            current_debt=Decimal('0.00'),
            can_pay_with_credit=True,
            active=True
        )

    def test_process_order_payment_with_balance_only(self):
        """Test process_order_payment using only balance"""
        from orders.services import process_order_payment
        order_amount = Decimal('300.00')

        result = process_order_payment(
            client=self.client,
            order_amount=order_amount,
            preferred_method='balance',
            user=self.user
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['balance_used'], order_amount)
        self.assertEqual(result['credit_used'], Decimal('0'))
        self.client.refresh_from_db()
        self.assertEqual(self.client.balance, Decimal('200.00'))

    def test_process_order_payment_with_credit_only(self):
        """Test process_order_payment using only credit"""
        from orders.services import process_order_payment
        order_amount = Decimal('1000.00')

        result = process_order_payment(
            client=self.client,
            order_amount=order_amount,
            preferred_method='credit',
            user=self.user
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['balance_used'], Decimal('0'))
        self.assertEqual(result['credit_used'], order_amount)
        self.client.refresh_from_db()
        self.assertEqual(self.client.current_debt, order_amount)

    def test_process_order_payment_auto_uses_balance_first(self):
        """Test process_order_payment auto mode uses balance first, then credit"""
        from orders.services import process_order_payment
        order_amount = Decimal('1000.00')

        result = process_order_payment(
            client=self.client,
            order_amount=order_amount,
            preferred_method='auto',
            user=self.user
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['balance_used'], Decimal('500.00'))
        self.assertEqual(result['credit_used'], Decimal('500.00'))
        self.client.refresh_from_db()
        self.assertEqual(self.client.balance, Decimal('0.00'))
        self.assertEqual(self.client.current_debt, Decimal('500.00'))

    def test_process_order_payment_insufficient_balance_fails(self):
        """Test process_order_payment fails when balance insufficient and credit disabled"""
        from orders.services import process_order_payment
        self.client.can_pay_with_credit = False
        self.client.save()

        order_amount = Decimal('1000.00')

        result = process_order_payment(
            client=self.client,
            order_amount=order_amount,
            preferred_method='balance',
            user=self.user
        )

        self.assertFalse(result['success'])
        self.assertIn('error', result)

    def test_process_order_payment_requires_note_for_credit(self):
        """Test process_order_payment requires note when configured"""
        from orders.services import process_order_payment
        self.client.requires_note_for_credit = True
        self.client.save()

        order_amount = Decimal('1000.00')

        # Without note - should fail
        result = process_order_payment(
            client=self.client,
            order_amount=order_amount,
            preferred_method='credit',
            user=self.user
        )

        self.assertFalse(result['success'])
        self.assertTrue(result.get('note_required', False))

    def test_process_order_payment_with_note_succeeds(self):
        """Test process_order_payment with note when required"""
        from orders.services import process_order_payment
        self.client.requires_note_for_credit = True
        self.client.save()

        order_amount = Decimal('1000.00')

        result = process_order_payment(
            client=self.client,
            order_amount=order_amount,
            preferred_method='credit',
            user=self.user,
            credit_note="Approved purchase"
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['credit_used'], order_amount)

    def test_can_afford_order_with_balance_and_credit(self):
        """Test can_afford_order considers both balance and available credit"""
        order_amount = Decimal('2000.00')
        # Balance: 500, Available credit: 2000
        self.assertTrue(self.client.can_afford_order(order_amount))

    def test_cannot_afford_order_exceeding_resources(self):
        """Test can_afford_order returns False when amount exceeds resources"""
        order_amount = Decimal('3000.00')
        # Balance: 500, Available credit: 2000, Total: 2500
        self.assertFalse(self.client.can_afford_order(order_amount))

    def test_can_use_credit_for_payment_when_enabled(self):
        """Test can_use_credit_for_payment returns True when enabled"""
        self.assertTrue(self.client.can_use_credit_for_payment())

    def test_can_use_credit_for_payment_when_disabled_with_available_credit(self):
        """Test can_use_credit_for_payment with disabled credit but available limit"""
        self.client.can_pay_with_credit = False
        self.client.save()

        # Still has available credit
        self.assertTrue(self.client.can_use_credit_for_payment())

    def test_can_use_credit_for_payment_when_disabled_no_available_credit(self):
        """Test can_use_credit_for_payment when disabled and no available credit"""
        self.client.can_pay_with_credit = False
        self.client.current_debt = Decimal('2000.00')  # At limit
        self.client.save()

        self.assertFalse(self.client.can_use_credit_for_payment())


class ClientBalanceTransferTestCase(TestCase):
    """Test cases for balance transfers between clients"""

    def setUp(self):
        """Set up test data for transfer tests"""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.source_client = Client.objects.create(
            name="Source Client",
            type="corporate",
            balance=Decimal('1000.00'),
            active=True
        )
        self.target_client = Client.objects.create(
            name="Target Client",
            type="corporate",
            balance=Decimal('500.00'),
            active=True
        )

    def test_transfer_balance_success(self):
        """Test successful balance transfer between clients"""
        from clients.services import balance_service
        amount = Decimal('300.00')

        result = balance_service.transfer_balance(
            from_client=self.source_client,
            to_client=self.target_client,
            amount=amount,
            user=self.user,
            notes="Test transfer"
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['amount_transferred'], amount)

        # Refresh from database
        self.source_client.refresh_from_db()
        self.target_client.refresh_from_db()

        self.assertEqual(self.source_client.balance, Decimal('700.00'))
        self.assertEqual(self.target_client.balance, Decimal('800.00'))

    def test_transfer_balance_insufficient_funds(self):
        """Test transfer fails with insufficient balance"""
        from clients.services import balance_service
        amount = Decimal('2000.00')

        result = balance_service.transfer_balance(
            from_client=self.source_client,
            to_client=self.target_client,
            amount=amount,
            user=self.user
        )

        self.assertFalse(result['success'])
        self.assertIn('error', result)

    def test_transfer_balance_creates_transactions(self):
        """Test transfer creates transactions for both clients"""
        from clients.services import balance_service
        amount = Decimal('300.00')

        balance_service.transfer_balance(
            from_client=self.source_client,
            to_client=self.target_client,
            amount=amount,
            user=self.user
        )

        # Check source transaction
        source_tx = BalanceTransaction.objects.filter(
            client=self.source_client,
            transaction_type='transfer_out'
        ).first()
        self.assertIsNotNone(source_tx)
        self.assertEqual(source_tx.amount, amount)

        # Check target transaction
        target_tx = BalanceTransaction.objects.filter(
            client=self.target_client,
            transaction_type='transfer_in'
        ).first()
        self.assertIsNotNone(target_tx)
        self.assertEqual(target_tx.amount, amount)


class ClientHistoryTestCase(TestCase):
    """Test cases for client transaction history using managers"""

    def setUp(self):
        """Set up test data for history tests"""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client = Client.objects.create(
            name="Test Client",
            type="corporate",
            balance=Decimal('1000.00'),
            credit_limit=Decimal('5000.00'),
            current_debt=Decimal('0.00'),
            can_pay_with_credit=True,
            active=True
        )

    def test_get_balance_history(self):
        """Test BalanceTransaction manager returns transactions"""
        from clients.services import balance_service
        balance_service.add_balance(client=self.client, amount=Decimal('500.00'), user=self.user)
        balance_service.deduct_balance(client=self.client, amount=Decimal('200.00'), user=self.user)

        history = BalanceTransaction.objects.for_client(self.client)
        self.assertEqual(history.count(), 2)

    def test_get_balance_history_filtered_by_date(self):
        """Test BalanceTransaction manager with date filtering"""
        from clients.services import balance_service
        balance_service.add_balance(client=self.client, amount=Decimal('500.00'), user=self.user)

        # Filter by today onwards
        today = date.today()
        history = BalanceTransaction.objects.for_client(self.client).in_date_range(start_date=today)
        self.assertEqual(history.count(), 1)

    def test_get_balance_history_filtered_by_type(self):
        """Test BalanceTransaction manager with transaction type filtering"""
        from clients.services import balance_service
        balance_service.add_balance(client=self.client, amount=Decimal('500.00'), transaction_type='deposit', user=self.user)
        balance_service.deduct_balance(client=self.client, amount=Decimal('200.00'), transaction_type='payment', user=self.user)

        history = BalanceTransaction.objects.for_client(self.client).by_types(['deposit'])
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().transaction_type, 'deposit')

    def test_get_credit_history(self):
        """Test CreditTransaction manager returns transactions"""
        from clients.services import balance_service
        balance_service.add_debt(client=self.client, amount=Decimal('1000.00'), user=self.user)
        balance_service.pay_debt(client=self.client, amount=Decimal('500.00'), user=self.user)

        history = CreditTransaction.objects.for_client(self.client)
        self.assertEqual(history.count(), 2)

    def test_get_balance_at_date(self):
        """Test BalanceTransaction manager balance_at returns correct historical balance"""
        from clients.services import balance_service
        # Initial balance transaction
        balance_service.add_balance(client=self.client, amount=Decimal('500.00'), user=self.user)

        # Get balance at tomorrow (to include today's transactions)
        balance = BalanceTransaction.objects.for_client(self.client).balance_at(date.today() + timedelta(days=1))
        self.assertEqual(balance, Decimal('1500.00'))  # 1000 initial + 500 added

    def test_get_debt_at_date(self):
        """Test CreditTransaction manager debt_at returns correct historical debt"""
        from clients.services import balance_service
        balance_service.add_debt(client=self.client, amount=Decimal('1000.00'), user=self.user)

        debt = CreditTransaction.objects.for_client(self.client).debt_at(date.today() + timedelta(days=1))
        self.assertEqual(debt, Decimal('1000.00'))

    def test_get_financial_summary(self):
        """Test get_financial_summary service returns comprehensive data"""
        from clients.services import balance_service
        balance_service.add_balance(client=self.client, amount=Decimal('500.00'), transaction_type='deposit', user=self.user)
        balance_service.deduct_balance(client=self.client, amount=Decimal('200.00'), transaction_type='payment', user=self.user)
        balance_service.add_debt(client=self.client, amount=Decimal('1000.00'), transaction_type='purchase', user=self.user)

        summary = balance_service.get_financial_summary(self.client)

        self.client.refresh_from_db()
        self.assertEqual(summary['current_balance'], self.client.balance)
        self.assertEqual(summary['current_debt'], self.client.current_debt)
        self.assertIn('balance_summary', summary)
        self.assertIn('credit_summary', summary)


class AddressValidationTestCase(TestCase):
    """Test cases for Address model validation"""

    def setUp(self):
        """Set up test data for address tests"""
        self.client = Client.objects.create(
            name="Test Client",
            type="corporate",
            active=True
        )

    def test_one_billing_address_per_client(self):
        """Test that only one billing address is allowed per client"""
        # Create first billing address
        Address.objects.create(
            client=self.client,
            type="billing",
            street="First Street",
            municipality="Querétaro",
            active=True
        )

        # Try to create second billing address
        second_address = Address(
            client=self.client,
            type="billing",
            street="Second Street",
            municipality="Querétaro",
            active=True
        )

        with self.assertRaises(ValidationError):
            second_address.clean()

    def test_one_shipping_address_per_client(self):
        """Test that only one shipping address is allowed per client"""
        # Create first shipping address
        Address.objects.create(
            client=self.client,
            type="shipping",
            street="First Street",
            municipality="Querétaro",
            active=True
        )

        # Try to create second shipping address
        second_address = Address(
            client=self.client,
            type="shipping",
            street="Second Street",
            municipality="Querétaro",
            active=True
        )

        with self.assertRaises(ValidationError):
            second_address.clean()

    def test_multiple_other_addresses_allowed(self):
        """Test that multiple 'other' type addresses are allowed"""
        Address.objects.create(
            client=self.client,
            type="other",
            street="First Street",
            municipality="Querétaro",
            active=True
        )

        second_address = Address(
            client=self.client,
            type="other",
            street="Second Street",
            municipality="Querétaro",
            active=True
        )

        # Should not raise ValidationError
        try:
            second_address.clean()
        except ValidationError:
            self.fail("Multiple 'other' type addresses should be allowed")


class ContactModelTestCase(TestCase):
    """Test cases for Contact model"""

    def setUp(self):
        """Set up test data for contact tests"""
        self.client = Client.objects.create(
            name="Test Client",
            type="corporate",
            active=True
        )

    def test_create_contact(self):
        """Test creating a contact for a client"""
        contact = Contact.objects.create(
            client=self.client,
            name="John Doe",
            email="john@example.com",
            phone="1234567890",
            position="Manager"
        )

        self.assertEqual(contact.client, self.client)
        self.assertEqual(contact.name, "John Doe")
        self.assertEqual(str(contact), "John Doe (1234567890)")

    def test_multiple_contacts_per_client(self):
        """Test that multiple contacts can be associated with one client"""
        Contact.objects.create(
            client=self.client,
            name="John Doe",
            email="john@example.com",
            phone="1111111111"
        )
        Contact.objects.create(
            client=self.client,
            name="Jane Smith",
            email="jane@example.com",
            phone="2222222222"
        )

        self.assertEqual(self.client.contacts.count(), 2)


class BillingDataModelTestCase(TestCase):
    """Test cases for BillingData model"""

    def setUp(self):
        """Set up test data for billing data tests"""
        self.client = Client.objects.create(
            name="Test Client",
            type="corporate",
            active=True
        )

    def test_create_billing_data(self):
        """Test creating billing data for a client"""
        billing = BillingData.objects.create(
            client=self.client,
            rfc="TEST123456ABC",
            razon_social="Test Company SA de CV",
            curp="CURP123456HDFABC01"
        )

        self.assertEqual(billing.client, self.client)
        self.assertEqual(billing.rfc, "TEST123456ABC")
        self.assertEqual(str(billing), f"Billing data for {self.client.name}")


class ClientUpdateServiceTestCase(TestCase):
    """Test cases for the update_client service method"""

    def setUp(self):
        """Set up test data for client update tests"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        # Create a client with billing enabled
        self.client = Client.objects.create(
            name="Test Client with Billing",
            type="corporate",
            active=True,
            requires_billing=True
        )

    def test_disable_requires_billing_removes_billing_data_and_frequency(self):
        """
        Test that when requires_billing is set to False,
        the client's billing data and billing frequency are removed/deactivated
        """
        from clients.services.client_service import update_client, ClientUpdateData
        
        # Create billing data for the client
        billing_data = BillingData.objects.create(
            client=self.client,
            rfc="TEST123456ABC",
            razon_social="Test Company SA de CV"
        )
        
        # Create billing address
        billing_address = Address.objects.create(
            client=self.client,
            type="billing",
            street="Av. Test 100",
            municipality="Test City",
            state="Test State",
            zip_code="12345",
            country="México",
            active=True
        )
        
        # Create billing frequency
        billing_frequency = ClientBillingFrecuency.objects.create(
            client=self.client,
            frequency="monthly",
            billing_date="last_day",
            is_active=True
        )
        
        # Verify initial setup
        self.assertTrue(self.client.requires_billing)
        self.assertTrue(hasattr(self.client, 'billing_data'))
        self.assertTrue(hasattr(self.client, 'billing_frecuency'))
        self.assertTrue(BillingData.objects.filter(client=self.client).exists())
        self.assertTrue(ClientBillingFrecuency.objects.filter(client=self.client).exists())
        
        # Update client to disable billing
        update_data = ClientUpdateData(requires_billing=False)
        updated_client = update_client(self.client, update_data, self.user)
        
        # Refresh from database
        updated_client.refresh_from_db()
        
        # Verify requires_billing is now False
        self.assertFalse(updated_client.requires_billing)
        
        # Verify billing data has been deleted
        self.assertFalse(
            BillingData.objects.filter(client=updated_client).exists(),
            "Billing data should be deleted when requires_billing is False"
        )
        
        # Verify billing frequency has been deleted
        self.assertFalse(
            ClientBillingFrecuency.objects.filter(client=updated_client).exists(),
            "Billing frequency should be deleted when requires_billing is False"
        )
    
    def test_disable_requires_billing_without_existing_billing_data(self):
        """
        Test that disabling requires_billing works even when
        the client doesn't have billing data or frequency
        """
        from clients.services.client_service import update_client, ClientUpdateData
        
        # Client already has requires_billing=True but no billing data/frequency
        self.assertTrue(self.client.requires_billing)
        self.assertFalse(hasattr(self.client, 'billing_data'))
        self.assertFalse(hasattr(self.client, 'billing_frecuency'))
        
        # Update client to disable billing
        update_data = ClientUpdateData(requires_billing=False)
        updated_client = update_client(self.client, update_data, self.user)
        
        # Refresh from database
        updated_client.refresh_from_db()
        
        # Verify requires_billing is now False
        self.assertFalse(updated_client.requires_billing)
        
        # Verify no billing data exists
        self.assertFalse(BillingData.objects.filter(client=updated_client).exists())
        self.assertFalse(ClientBillingFrecuency.objects.filter(client=updated_client).exists())
    
    def test_disable_requires_billing_with_billing_frequency(self):
        """
        Test that billing frequency is removed when requires_billing is disabled
        """
        from clients.services.client_service import update_client, ClientUpdateData
        
        # Create billing frequency
        billing_frequency = ClientBillingFrecuency.objects.create(
            client=self.client,
            frequency="monthly",
            billing_date="last_day",
            is_active=True
        )
        
        # Verify initial setup
        self.assertTrue(
            ClientBillingFrecuency.objects.filter(client=self.client).exists()
        )
        
        # Update client to disable billing
        update_data = ClientUpdateData(requires_billing=False)
        updated_client = update_client(self.client, update_data, self.user)
        
        # Refresh from database
        updated_client.refresh_from_db()
        
        # Verify billing frequency is deleted
        self.assertFalse(
            ClientBillingFrecuency.objects.filter(client=updated_client).exists(),
            "Billing frequency should be deleted when requires_billing is False"
        )


class BillingInfoTestCase(TestCase):
    """Comprehensive test cases for the new centralized BillingInfo class"""

    def setUp(self):
        """Set up test data for billing info tests"""
        # Create corporate client with complete billing setup
        self.corporate = Client.objects.create(
            name="Corporate Client",
            type="corporate",
            active=True
        )
        
        self.corporate_billing_data = BillingData.objects.create(
            client=self.corporate,
            rfc="CORP123456ABC",
            razon_social="Corporativo SA de CV"
        )
        
        self.corporate_billing_address = Address.objects.create(
            client=self.corporate,
            type="billing",
            street="Av. Corporativa 100",
            municipality="Querétaro",
            state="Querétaro",
            zip_code="76000",
            country="México",
            active=True
        )
        
        self.corporate_billing_frequency = ClientBillingFrecuency.objects.create(
            client=self.corporate,
            frequency="monthly",
            billing_date="first_day",
            is_active=True
        )
        
        # Create branch client (no own billing data initially)
        self.branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True
        )

    def test_billing_info_property_is_cached(self):
        """Test that billing_info is cached using @cached_property"""
        billing1 = self.corporate.billing_info
        billing2 = self.corporate.billing_info
        # Should be the same object instance (cached)
        self.assertIs(billing1, billing2)

    def test_own_billing_data_detects_all_components(self):
        """Test OwnBillingData correctly detects all billing components"""
        billing = self.corporate.billing_info
        
        self.assertTrue(billing.own.has_data)
        self.assertTrue(billing.own.has_address)
        self.assertTrue(billing.own.has_frequency)
        self.assertTrue(billing.own.is_complete)
        self.assertTrue(billing.own.has_any)

    def test_own_billing_data_detects_missing_components(self):
        """Test OwnBillingData correctly identifies missing components"""
        client_no_billing = Client.objects.create(
            name="Client No Billing",
            type="corporate",
            active=True
        )
        
        billing = client_no_billing.billing_info
        
        self.assertFalse(billing.own.has_data)
        self.assertFalse(billing.own.has_address)
        self.assertFalse(billing.own.has_frequency)
        self.assertFalse(billing.own.is_complete)
        self.assertFalse(billing.own.has_any)

    def test_effective_billing_inherits_from_corporate(self):
        """Test EffectiveBillingData correctly inherits from corporate for branch"""
        billing = self.branch.billing_info
        
        # Branch has no own data
        self.assertFalse(billing.own.has_data)
        self.assertFalse(billing.own.has_address)
        self.assertFalse(billing.own.has_frequency)
        
        # But effective data should come from corporate
        self.assertTrue(billing.effective.has_data)
        self.assertTrue(billing.effective.has_address)
        self.assertTrue(billing.effective.has_frequency)
        self.assertTrue(billing.effective.is_complete)
        
        # Verify actual data
        self.assertEqual(billing.effective.data.rfc, "CORP123456ABC")
        self.assertEqual(billing.effective.address.street, "Av. Corporativa 100")
        self.assertEqual(billing.effective.frequency.frequency, "monthly")

    def test_effective_billing_uses_own_when_available(self):
        """Test EffectiveBillingData uses own data when branch has it"""
        # Add branch-specific billing data
        branch_billing_data = BillingData.objects.create(
            client=self.branch,
            rfc="BRANCH123456XYZ",
            razon_social="Sucursal SA de CV"
        )
        
        branch_billing_address = Address.objects.create(
            client=self.branch,
            type="billing",
            street="Av. Sucursal 200",
            municipality="Querétaro",
            active=True
        )
        
        branch_billing_frequency = ClientBillingFrecuency.objects.create(
            client=self.branch,
            frequency="weekly",
            is_active=True
        )
        
        # Clear cache to get fresh billing_info
        if hasattr(self.branch, '_billing_info'):
            del self.branch._billing_info
        if hasattr(self.branch, 'billing_info'):
            del self.branch.__dict__['billing_info']
        
        billing = self.branch.billing_info
        
        # Should use own data, not inherited
        self.assertTrue(billing.own.is_complete)
        self.assertEqual(billing.effective.data.rfc, "BRANCH123456XYZ")
        self.assertEqual(billing.effective.address.street, "Av. Sucursal 200")
        self.assertEqual(billing.effective.frequency.frequency, "weekly")

    def test_billing_source_own_for_complete_setup(self):
        """Test source is 'own' when client has complete own billing"""
        billing = self.corporate.billing_info
        self.assertEqual(billing.source, 'own')
        self.assertFalse(billing.uses_inheritance)

    def test_billing_source_corporate_for_inheriting_branch(self):
        """Test source is 'corporate' when branch inherits from corporate"""
        billing = self.branch.billing_info
        self.assertEqual(billing.source, 'corporate')
        self.assertTrue(billing.uses_inheritance)

    def test_billing_source_none_without_data(self):
        """Test source is 'none' when no billing data available"""
        client_no_billing = Client.objects.create(
            name="Client No Billing",
            type="corporate",
            active=True
        )
        
        billing = client_no_billing.billing_info
        self.assertEqual(billing.source, 'none')
        self.assertFalse(billing.uses_inheritance)

    def test_billing_source_own_with_override_enabled(self):
        """Test source is 'own' when branch has override enabled with partial data"""
        # Enable override but only add partial data
        self.branch.billing_override_enabled = True
        self.branch.save()
        
        BillingData.objects.create(
            client=self.branch,
            rfc="BRANCH123456XYZ",
            razon_social="Sucursal SA de CV"
        )
        
        # Clear cache
        if hasattr(self.branch, 'billing_info'):
            del self.branch.__dict__['billing_info']
        
        billing = self.branch.billing_info
        
        # Should be 'own' even though incomplete
        self.assertEqual(billing.source, 'own')
        self.assertTrue(billing.own.has_any)
        self.assertFalse(billing.own.is_complete)

    def test_is_complete_property(self):
        """Test is_complete property accurately reflects completeness"""
        # Complete setup
        self.assertTrue(self.corporate.billing_info.is_complete)
        
        # Incomplete setup
        client_partial = Client.objects.create(
            name="Client Partial",
            type="corporate",
            active=True
        )
        BillingData.objects.create(
            client=client_partial,
            rfc="PARTIAL123ABC",
            razon_social="Partial SA"
        )
        
        self.assertFalse(client_partial.billing_info.is_complete)

    def test_can_create_invoice_property(self):
        """Test can_create_invoice property matches is_complete"""
        billing_complete = self.corporate.billing_info
        self.assertTrue(billing_complete.can_create_invoice)
        self.assertEqual(billing_complete.can_create_invoice, billing_complete.is_complete)
        
        client_incomplete = Client.objects.create(
            name="Client Incomplete",
            type="corporate",
            active=True
        )
        billing_incomplete = client_incomplete.billing_info
        self.assertFalse(billing_incomplete.can_create_invoice)

    def test_missing_components_list(self):
        """Test missing_components returns correct list of missing items"""
        # No missing components
        self.assertEqual(self.corporate.billing_info.missing_components, [])
        
        # Missing all components
        client_empty = Client.objects.create(
            name="Client Empty",
            type="corporate",
            active=True
        )
        self.assertEqual(
            set(client_empty.billing_info.missing_components),
            {'billing_data', 'billing_address', 'billing_frequency'}
        )
        
        # Missing only frequency
        client_partial = Client.objects.create(
            name="Client Partial",
            type="corporate",
            active=True
        )
        BillingData.objects.create(
            client=client_partial,
            rfc="PARTIAL123ABC",
            razon_social="Partial SA"
        )
        Address.objects.create(
            client=client_partial,
            type="billing",
            street="Partial Street",
            municipality="Querétaro",
            active=True
        )
        
        self.assertEqual(
            client_partial.billing_info.missing_components,
            ['billing_frequency']
        )

    def test_get_setup_status_backward_compatibility(self):
        """Test get_setup_status() maintains backward compatibility"""
        status = self.corporate.billing_info.get_setup_status()
        
        self.assertIsInstance(status, dict)
        self.assertIn('is_complete', status)
        self.assertIn('source', status)
        self.assertIn('missing_components', status)
        
        self.assertTrue(status['is_complete'])
        self.assertEqual(status['source'], 'own')
        self.assertEqual(status['missing_components'], [])

    def test_get_override_validation_warnings_with_incomplete_data(self):
        """Test override validation warnings when branch has incomplete own data"""
        self.branch.billing_override_enabled = True
        self.branch.save()
        
        # Clear cache
        if hasattr(self.branch, 'billing_info'):
            del self.branch.__dict__['billing_info']
        
        warnings = self.branch.billing_info.get_override_validation_warnings()
        
        self.assertEqual(len(warnings), 3)  # Missing all 3 components
        self.assertTrue(any('RFC' in w for w in warnings))
        self.assertTrue(any('Dirección fiscal' in w for w in warnings))
        self.assertTrue(any('Frecuencia' in w for w in warnings))

    def test_get_override_validation_warnings_with_complete_data(self):
        """Test no warnings when branch with override has complete data"""
        self.branch.billing_override_enabled = True
        self.branch.save()
        
        # Add complete billing data
        BillingData.objects.create(
            client=self.branch,
            rfc="BRANCH123456XYZ",
            razon_social="Sucursal SA de CV"
        )
        Address.objects.create(
            client=self.branch,
            type="billing",
            street="Branch Street",
            municipality="Querétaro",
            active=True
        )
        ClientBillingFrecuency.objects.create(
            client=self.branch,
            frequency="monthly",
            is_active=True
        )
        
        # Clear cache
        if hasattr(self.branch, 'billing_info'):
            del self.branch.__dict__['billing_info']
        
        warnings = self.branch.billing_info.get_override_validation_warnings()
        self.assertEqual(len(warnings), 0)

    def test_get_override_validation_warnings_without_override(self):
        """Test no warnings when override is disabled"""
        warnings = self.branch.billing_info.get_override_validation_warnings()
        self.assertEqual(len(warnings), 0)

    def test_override_prevents_inheritance(self):
        """Test that billing_override_enabled prevents inheritance"""
        self.branch.billing_override_enabled = True
        self.branch.save()
        
        # Clear cache
        if hasattr(self.branch, 'billing_info'):
            del self.branch.__dict__['billing_info']
        
        billing = self.branch.billing_info
        
        # Should NOT inherit from corporate
        self.assertIsNone(billing.effective.data)
        self.assertIsNone(billing.effective.address)
        self.assertIsNone(billing.effective.frequency)
        self.assertFalse(billing.effective.is_complete)

