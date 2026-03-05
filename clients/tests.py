from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date, timedelta
from .models import (
    Client, BillingData, Address, BalanceTransaction, CreditTransaction,
    Contact, ClientBillingFrecuency, ClientCreditConfig
)
from .forms import AddressInlineForm

User = get_user_model()


class ClientBillingInheritanceTestCase(TestCase):
    """Business-rule focused tests for billing inheritance/override."""

    def setUp(self):
        self.corporate = Client.objects.create(
            name="Corporate Client",
            type="corporate",
            requires_billing=True,
            active=True,
        )
        BillingData.objects.create(
            client=self.corporate,
            rfc="CORP123456ABC",
            razon_social="Corporativo SA de CV",
        )
        Address.objects.create(
            client=self.corporate,
            type="billing",
            street="Av. Corporativa 100",
            municipality="Querétaro",
            state="Querétaro",
            zip_code="76000",
            country="México",
            active=True,
        )
        ClientBillingFrecuency.objects.create(
            client=self.corporate,
            frequency="monthly",
            billing_date="first_day",
            is_active=True,
        )

        self.branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True,
        )

        self.branch_override = Client.objects.create(
            name="Branch Override",
            type="branch",
            corporate=self.corporate,
            billing_override_enabled=True,
            requires_billing=True,
            active=True,
        )

    def test_corporate_ready_with_all_components(self):
        billing = self.corporate.billing_info
        self.assertTrue(billing.is_complete)
        self.assertEqual(billing.source, 'own')

    def test_corporate_not_ready_when_missing_any_component(self):
        corporate = Client.objects.create(
            name="Corp Missing Address",
            type="corporate",
            requires_billing=True,
            active=True,
        )
        BillingData.objects.create(
            client=corporate,
            rfc="MISS123456",
            razon_social="Missing SA",
        )
        ClientBillingFrecuency.objects.create(
            client=corporate,
            frequency="monthly",
            billing_date="first_day",
            is_active=True,
        )

        billing = corporate.billing_info
        self.assertFalse(billing.is_complete)
        self.assertEqual(billing.source, 'none')

    def test_branch_inherits_when_corporate_ready(self):
        billing = self.branch.billing_info
        self.assertTrue(billing.is_complete)
        self.assertEqual(billing.source, 'corporate')

    def test_branch_inheritance_not_ready_if_corporate_incomplete(self):
        corp_incomplete = Client.objects.create(
            name="Corp Incomplete",
            type="corporate",
            requires_billing=True,
            active=True,
        )
        BillingData.objects.create(
            client=corp_incomplete,
            rfc="INC123456",
            razon_social="Incomplete SA",
        )
        ClientBillingFrecuency.objects.create(
            client=corp_incomplete,
            frequency="monthly",
            billing_date="first_day",
            is_active=True,
        )
        branch = Client.objects.create(
            name="Branch Inherit Incomplete",
            type="branch",
            corporate=corp_incomplete,
            active=True,
        )

        billing = branch.billing_info
        self.assertFalse(billing.is_complete)
        self.assertEqual(billing.source, 'corporate')

    def test_branch_override_ready_with_own_complete_data(self):
        BillingData.objects.create(
            client=self.branch_override,
            rfc="BRANCH123456XYZ",
            razon_social="Sucursal SA de CV",
        )
        Address.objects.create(
            client=self.branch_override,
            type="billing",
            street="Av. Sucursal 200",
            municipality="Querétaro",
            state="Querétaro",
            zip_code="76100",
            country="México",
            active=True,
        )
        ClientBillingFrecuency.objects.create(
            client=self.branch_override,
            frequency="monthly",
            billing_date="first_day",
            is_active=True,
        )

        billing = self.branch_override.billing_info
        self.assertTrue(billing.is_complete)
        self.assertEqual(billing.source, 'own')

    def test_branch_override_not_ready_with_incomplete_own_data(self):
        BillingData.objects.create(
            client=self.branch_override,
            rfc="PART123456",
            razon_social="Parcial SA",
        )
        # Missing address and frequency
        billing = self.branch_override.billing_info
        self.assertFalse(billing.is_complete)
        self.assertEqual(billing.source, 'own')


class AddressInlineFormTests(TestCase):
    """Tests for AddressInlineForm and its same_as_previous helper field."""

    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Test Address Client",
            type="corporate",
            requires_billing=True,
            active=True,
        )

    def test_form_has_same_as_previous_field(self) -> None:
        """The inline form must expose the non-model boolean field."""
        form = AddressInlineForm()
        self.assertIn('same_as_previous', form.fields)

    def test_same_as_previous_is_not_required(self) -> None:
        """The checkbox must be optional."""
        field = AddressInlineForm().fields['same_as_previous']
        self.assertFalse(field.required)

    def test_same_as_previous_label(self) -> None:
        """The checkbox label must match the spec."""
        field = AddressInlineForm().fields['same_as_previous']
        self.assertEqual(field.label, "Misma dirección que la anterior")

    def test_form_valid_without_same_as_previous(self) -> None:
        """Submitting without the helper field must not cause validation errors."""
        data = {
            'client': self.client_obj.pk,
            'type': 'shipping',
            'street': 'Av. Test 1',
            'locality': 'Querétaro',
            'municipality': 'Querétaro',
            'state': 'Querétaro',
            'zip_code': '76000',
            'country': 'Mexico',
        }
        form = AddressInlineForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_billing_uniqueness_still_enforced(self) -> None:
        """Existing billing uniqueness via Address.clean() must remain intact."""
        Address.objects.create(
            client=self.client_obj,
            type='billing',
            street='Av. First 1',
            locality='Querétaro',
            municipality='Querétaro',
            state='Querétaro',
            zip_code='76000',
            country='Mexico',
        )
        duplicate = Address(
            client=self.client_obj,
            type='billing',
            street='Av. Second 2',
            locality='Querétaro',
            municipality='Querétaro',
            state='Querétaro',
            zip_code='76000',
            country='Mexico',
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()


