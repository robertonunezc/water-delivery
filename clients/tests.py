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
        self.assertIn('dirección de envío', error_msg.lower())

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
        initial_balance = self.client.balance
        amount = Decimal('500.00')

        new_balance = self.client.add_balance(
            amount=amount,
            transaction_type='deposit',
            user=self.user,
            notes="Test deposit"
        )

        self.assertEqual(new_balance, initial_balance + amount)
        self.assertEqual(self.client.balance, initial_balance + amount)

    def test_add_balance_creates_transaction_record(self):
        """Test that add_balance creates a BalanceTransaction record"""
        amount = Decimal('500.00')

        self.client.add_balance(
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
        with self.assertRaises(ValueError):
            self.client.add_balance(
                amount=Decimal('-100.00'),
                transaction_type='deposit',
                user=self.user
            )

    def test_deduct_balance_decreases_balance(self):
        """Test that deduct_balance decreases client balance"""
        initial_balance = self.client.balance
        amount = Decimal('300.00')

        success = self.client.deduct_balance(
            amount=amount,
            transaction_type='payment',
            user=self.user,
            notes="Test payment"
        )

        self.assertTrue(success)
        self.assertEqual(self.client.balance, initial_balance - amount)

    def test_deduct_balance_with_insufficient_funds_fails(self):
        """Test that deduct_balance fails with insufficient balance"""
        amount = Decimal('2000.00')  # More than current balance

        success = self.client.deduct_balance(
            amount=amount,
            transaction_type='payment',
            user=self.user
        )

        self.assertFalse(success)
        self.assertEqual(self.client.balance, Decimal('1000.00'))  # Unchanged

    def test_deduct_balance_creates_transaction_record(self):
        """Test that deduct_balance creates a BalanceTransaction record"""
        amount = Decimal('200.00')

        self.client.deduct_balance(
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
        initial_debt = self.client.current_debt
        amount = Decimal('500.00')

        success = self.client.add_debt(
            amount=amount,
            transaction_type='purchase',
            user=self.user,
            notes="Test purchase"
        )

        self.assertTrue(success)
        self.assertEqual(self.client.current_debt, initial_debt + amount)

    def test_add_debt_creates_transaction_record(self):
        """Test that add_debt creates a CreditTransaction record"""
        amount = Decimal('500.00')

        self.client.add_debt(
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
        amount = Decimal('6000.00')  # Exceeds available credit

        success = self.client.add_debt(
            amount=amount,
            transaction_type='purchase',
            user=self.user
        )

        self.assertTrue(success)
        self.assertEqual(self.client.current_debt, Decimal('7000.00'))

    def test_add_debt_exceeding_limit_with_can_pay_credit_false_fails(self):
        """Test that add_debt blocks exceeding limit when can_pay_with_credit is False"""
        self.client.can_pay_with_credit = False
        self.client.save()

        amount = Decimal('5000.00')  # Would exceed limit

        success = self.client.add_debt(
            amount=amount,
            transaction_type='purchase',
            user=self.user
        )

        self.assertFalse(success)
        self.assertEqual(self.client.current_debt, Decimal('1000.00'))  # Unchanged

    def test_pay_debt_decreases_debt(self):
        """Test that pay_debt decreases current debt"""
        initial_debt = self.client.current_debt
        amount = Decimal('500.00')

        paid = self.client.pay_debt(
            amount=amount,
            transaction_type='payment',
            user=self.user
        )

        self.assertEqual(paid, amount)
        self.assertEqual(self.client.current_debt, initial_debt - amount)

    def test_pay_debt_limited_by_current_debt(self):
        """Test that pay_debt is limited by current debt amount"""
        amount = Decimal('2000.00')  # More than current debt

        paid = self.client.pay_debt(
            amount=amount,
            transaction_type='payment',
            user=self.user
        )

        self.assertEqual(paid, Decimal('1000.00'))  # Only paid existing debt
        self.assertEqual(self.client.current_debt, Decimal('0.00'))

    def test_get_available_credit(self):
        """Test get_available_credit returns correct amount"""
        available = self.client.get_available_credit()
        expected = Decimal('4000.00')  # 5000 limit - 1000 debt
        self.assertEqual(available, expected)

    def test_update_credit_limit(self):
        """Test update_credit_limit changes limit and creates transaction"""
        new_limit = Decimal('10000.00')

        self.client.update_credit_limit(
            new_limit=new_limit,
            user=self.user,
            notes="Increasing credit limit"
        )

        self.assertEqual(self.client.credit_limit, new_limit)

        transaction = CreditTransaction.objects.filter(
            client=self.client,
            transaction_type='limit_change'
        ).first()
        self.assertIsNotNone(transaction)

    def test_pay_debt_from_balance_success(self):
        """Test pay_debt_from_balance with sufficient balance"""
        self.client.balance = Decimal('500.00')
        self.client.save()

        amount = Decimal('300.00')
        result = self.client.pay_debt_from_balance(
            amount=amount,
            user=self.user
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['amount_paid'], amount)
        self.assertEqual(self.client.balance, Decimal('200.00'))
        self.assertEqual(self.client.current_debt, Decimal('700.00'))

    def test_pay_debt_from_balance_insufficient_balance(self):
        """Test pay_debt_from_balance fails with insufficient balance"""
        self.client.balance = Decimal('100.00')
        self.client.save()

        amount = Decimal('300.00')
        result = self.client.pay_debt_from_balance(
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
        order_amount = Decimal('300.00')

        result = self.client.process_order_payment(
            order_amount=order_amount,
            preferred_method='balance',
            user=self.user
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['balance_used'], order_amount)
        self.assertEqual(result['credit_used'], Decimal('0.00'))
        self.assertEqual(self.client.balance, Decimal('200.00'))

    def test_process_order_payment_with_credit_only(self):
        """Test process_order_payment using only credit"""
        order_amount = Decimal('1000.00')

        result = self.client.process_order_payment(
            order_amount=order_amount,
            preferred_method='credit',
            user=self.user
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['balance_used'], Decimal('0.00'))
        self.assertEqual(result['credit_used'], order_amount)
        self.assertEqual(self.client.current_debt, order_amount)

    def test_process_order_payment_auto_uses_balance_first(self):
        """Test process_order_payment auto mode uses balance first, then credit"""
        order_amount = Decimal('1000.00')

        result = self.client.process_order_payment(
            order_amount=order_amount,
            preferred_method='auto',
            user=self.user
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['balance_used'], Decimal('500.00'))
        self.assertEqual(result['credit_used'], Decimal('500.00'))
        self.assertEqual(self.client.balance, Decimal('0.00'))
        self.assertEqual(self.client.current_debt, Decimal('500.00'))

    def test_process_order_payment_insufficient_balance_fails(self):
        """Test process_order_payment fails when balance insufficient and credit disabled"""
        self.client.can_pay_with_credit = False
        self.client.save()

        order_amount = Decimal('1000.00')

        result = self.client.process_order_payment(
            order_amount=order_amount,
            preferred_method='balance',
            user=self.user
        )

        self.assertFalse(result['success'])
        self.assertIn('error', result)

    def test_process_order_payment_requires_note_for_credit(self):
        """Test process_order_payment requires note when configured"""
        self.client.requires_note_for_credit = True
        self.client.save()

        order_amount = Decimal('1000.00')

        # Without note - should fail
        result = self.client.process_order_payment(
            order_amount=order_amount,
            preferred_method='credit',
            user=self.user
        )

        self.assertFalse(result['success'])
        self.assertTrue(result.get('note_required', False))

    def test_process_order_payment_with_note_succeeds(self):
        """Test process_order_payment with note when required"""
        self.client.requires_note_for_credit = True
        self.client.save()

        order_amount = Decimal('1000.00')

        result = self.client.process_order_payment(
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
        amount = Decimal('300.00')

        result = self.source_client.transfer_balance_to(
            target_client=self.target_client,
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
        amount = Decimal('2000.00')

        result = self.source_client.transfer_balance_to(
            target_client=self.target_client,
            amount=amount,
            user=self.user
        )

        self.assertFalse(result['success'])
        self.assertIn('error', result)

    def test_transfer_balance_creates_transactions(self):
        """Test transfer creates transactions for both clients"""
        amount = Decimal('300.00')

        self.source_client.transfer_balance_to(
            target_client=self.target_client,
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
    """Test cases for client transaction history"""

    def setUp(self):
        """Set up test data for history tests"""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client = Client.objects.create(
            name="Test Client",
            type="corporate",
            balance=Decimal('1000.00'),
            credit_limit=Decimal('5000.00'),
            current_debt=Decimal('0.00'),
            active=True
        )

    def test_get_balance_history(self):
        """Test get_balance_history returns transactions"""
        self.client.add_balance(Decimal('500.00'), user=self.user)
        self.client.deduct_balance(Decimal('200.00'), user=self.user)

        history = self.client.get_balance_history()
        self.assertEqual(history.count(), 2)

    def test_get_balance_history_filtered_by_date(self):
        """Test get_balance_history with date filtering"""
        self.client.add_balance(Decimal('500.00'), user=self.user)

        # Filter by today onwards
        today = date.today()
        history = self.client.get_balance_history(start_date=today)
        self.assertEqual(history.count(), 1)

    def test_get_balance_history_filtered_by_type(self):
        """Test get_balance_history with transaction type filtering"""
        self.client.add_balance(Decimal('500.00'), transaction_type='deposit', user=self.user)
        self.client.deduct_balance(Decimal('200.00'), transaction_type='payment', user=self.user)

        history = self.client.get_balance_history(transaction_types=['deposit'])
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().transaction_type, 'deposit')

    def test_get_credit_history(self):
        """Test get_credit_history returns transactions"""
        self.client.add_debt(Decimal('1000.00'), user=self.user)
        self.client.pay_debt(Decimal('500.00'), user=self.user)

        history = self.client.get_credit_history()
        self.assertEqual(history.count(), 2)

    def test_get_balance_at_date(self):
        """Test get_balance_at_date returns correct historical balance"""
        # Initial balance transaction
        self.client.add_balance(Decimal('500.00'), user=self.user)

        # Get balance at today
        balance = self.client.get_balance_at_date(date.today() + timedelta(days=1))
        self.assertEqual(balance, Decimal('1500.00'))  # 1000 initial + 500 added

    def test_get_debt_at_date(self):
        """Test get_debt_at_date returns correct historical debt"""
        self.client.add_debt(Decimal('1000.00'), user=self.user)

        debt = self.client.get_debt_at_date(date.today() + timedelta(days=1))
        self.assertEqual(debt, Decimal('1000.00'))

    def test_get_financial_summary(self):
        """Test get_financial_summary returns comprehensive data"""
        self.client.add_balance(Decimal('500.00'), transaction_type='deposit', user=self.user)
        self.client.deduct_balance(Decimal('200.00'), transaction_type='payment', user=self.user)
        self.client.add_debt(Decimal('1000.00'), transaction_type='purchase', user=self.user)

        summary = self.client.get_financial_summary()

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
