import json
from calendar import monthrange
from datetime import timedelta
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from clients.admin import ClientAdmin, ClientCreditConfigInline
from clients.forms import ClientCoreForm, ClientCreditConfigForm, ClientCreditPolicyForm
from clients.models import Client, ClientCreditConfig
from clients.services import balance_service
from clients.services.pending_payment_service import client_has_overdue_credit
from orders.models import Order
from tenant_client.test_utils import FastTenantTestCase


User = get_user_model()


class CreditFormFieldTests(SimpleTestCase):
    def test_basic_form_does_not_expose_credit_fields(self) -> None:
        form = ClientCoreForm()

        self.assertNotIn('can_pay_with_credit', form.fields)
        self.assertNotIn('requires_note_for_credit', form.fields)
        self.assertNotIn('credit_limit', form.fields)

    def test_credit_config_form_only_exposes_payment_terms(self) -> None:
        form = ClientCreditConfigForm()

        self.assertEqual(
            list(form.fields),
            ['payment_term_type', 'cutoff_day', 'max_payment_days'],
        )

    def test_credit_policy_fields_include_business_help_text(self) -> None:
        form = ClientCreditPolicyForm()

        self.assertEqual(
            form.fields['can_pay_with_credit'].label,
            'Cliente no puede pagar con credito',
        )
        self.assertEqual(
            form.fields['credit_limit'].help_text,
            'Monto máximo de deuda activa autorizado.',
        )


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
    def test_credit_policy_checkbox_is_emergency_stop(self) -> None:
        client = Client.objects.create(
            name='Cliente con crédito permitido',
            type='corporate',
            can_pay_with_credit=True,
            credit_limit=Decimal('500.00'),
        )

        form = ClientCreditPolicyForm(
            data={
                'can_pay_with_credit': 'on',
                'credit_limit': '500.00',
            },
            instance=client,
        )

        self.assertTrue(form.is_valid(), form.errors)
        updated_client = form.save(commit=False)
        self.assertFalse(updated_client.can_pay_with_credit)

    def test_credit_policy_checkbox_unchecked_allows_credit(self) -> None:
        client = Client.objects.create(
            name='Cliente con crédito bloqueado',
            type='corporate',
            can_pay_with_credit=False,
            credit_limit=Decimal('500.00'),
        )

        form = ClientCreditPolicyForm(
            data={
                'credit_limit': '500.00',
            },
            instance=client,
        )

        self.assertTrue(form.is_valid(), form.errors)
        updated_client = form.save(commit=False)
        self.assertTrue(updated_client.can_pay_with_credit)

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


class BranchCreditInitializationTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='branch-credit-create-admin',
            password='testpass123',
            is_staff=True,
        )
        self.client.force_login(self.user)

    def test_branch_creation_copies_corporate_credit_policy_only(self) -> None:
        corporate = Client.objects.create(
            name='Corporativo con crédito',
            type='corporate',
            credit_limit=Decimal('750.00'),
            current_debt=Decimal('320.00'),
            balance=Decimal('125.00'),
            can_pay_with_credit=False,
        )
        ClientCreditConfig.objects.create(
            client=corporate,
            payment_term_type='monthly_cutoff',
            cutoff_day='15',
            max_payment_days=45,
        )

        response = self.client.post(
            reverse('clients:create_v2'),
            data={
                'name': 'Sucursal copiada',
                'active': 'on',
                'type': 'branch',
                'corporate': corporate.pk,
                'external_id': '',
                'note': '',
                'address_link': '',
            },
        )

        self.assertEqual(response.status_code, 302)
        branch = Client.objects.get(name='Sucursal copiada')
        self.assertEqual(branch.credit_limit, Decimal('750.00'))
        self.assertFalse(branch.can_pay_with_credit)
        self.assertEqual(branch.current_debt, Decimal('0.00'))
        self.assertEqual(branch.balance, Decimal('0.00'))
        self.assertFalse(branch.credit_override_enabled)
        self.assertEqual(branch.credit_config.payment_term_type, 'monthly_cutoff')
        self.assertEqual(branch.credit_config.cutoff_day, '15')
        self.assertEqual(branch.credit_config.max_payment_days, 45)

    def test_branch_creation_sets_requires_billing_for_invoice_due_credit_terms(self) -> None:
        corporate = Client.objects.create(
            name='Corporativo factura crédito',
            type='corporate',
            requires_billing=True,
            credit_limit=Decimal('900.00'),
        )
        ClientCreditConfig.objects.create(
            client=corporate,
            payment_term_type='invoice_due',
            max_payment_days=20,
        )

        response = self.client.post(
            reverse('clients:create_v2'),
            data={
                'name': 'Sucursal con vencimiento factura',
                'active': 'on',
                'type': 'branch',
                'corporate': corporate.pk,
                'external_id': '',
                'note': '',
                'address_link': '',
            },
        )

        self.assertEqual(response.status_code, 302)
        branch = Client.objects.get(name='Sucursal con vencimiento factura')
        self.assertTrue(branch.requires_billing)
        self.assertEqual(branch.credit_config.payment_term_type, 'invoice_due')
        self.assertEqual(branch.credit_config.max_payment_days, 20)

    def test_branch_creation_with_credit_override_still_copies_corporate_credit(self) -> None:
        corporate = Client.objects.create(
            name='Corporativo copia inicial',
            type='corporate',
            credit_limit=Decimal('650.00'),
            can_pay_with_credit=False,
        )
        ClientCreditConfig.objects.create(
            client=corporate,
            payment_term_type='monthly_cutoff',
            cutoff_day='last_day',
            max_payment_days=35,
        )

        response = self.client.post(
            reverse('clients:create_v2'),
            data={
                'name': 'Sucursal copia editable',
                'active': 'on',
                'type': 'branch',
                'corporate': corporate.pk,
                'credit_override_enabled': 'on',
                'external_id': '',
                'note': '',
                'address_link': '',
            },
        )

        self.assertEqual(response.status_code, 302)
        branch = Client.objects.get(name='Sucursal copia editable')
        self.assertTrue(branch.credit_override_enabled)
        self.assertEqual(branch.credit_limit, Decimal('650.00'))
        self.assertFalse(branch.can_pay_with_credit)
        self.assertEqual(branch.credit_config.payment_term_type, 'monthly_cutoff')
        self.assertEqual(branch.credit_config.cutoff_day, 'last_day')
        self.assertEqual(branch.credit_config.max_payment_days, 35)


class BranchCreditTabTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='credit-tab-admin',
            password='testpass123',
            is_staff=True,
        )
        self.client.force_login(self.user)
        self.corporate = Client.objects.create(
            name='Corporativo con facturación',
            type='corporate',
            requires_billing=True,
        )
        self.branch = Client.objects.create(
            name='Sucursal heredada',
            type='branch',
            corporate=self.corporate,
            credit_limit=Decimal('1000.00'),
        )
        ClientCreditConfig.objects.create(client=self.branch)

    def test_branch_without_credit_override_sees_credit_tab_read_only(self) -> None:
        response = self.client.get(
            f"{reverse('clients:edit_v2', args=[self.branch.pk])}?tab=credit",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tab'], 'credit')
        self.assertTrue(response.context['credit_read_only'])
        self.assertContains(
            response,
            'La configuración de crédito se administra desde el corporativo',
        )

    def test_branch_without_credit_override_cannot_modify_its_credit(self) -> None:
        response = self.client.post(
            reverse('clients:edit_v2', args=[self.branch.pk]),
            data={
                'section': 'credit',
                'credit_policy-can_pay_with_credit': 'on',
                'credit_policy-credit_limit': '500.00',
                'credit_config-payment_term_type': 'monthly_cutoff',
                'credit_config-cutoff_day': 'last_day',
                'credit_config-max_payment_days': '30',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.credit_limit, Decimal('1000.00'))

    def test_branch_with_credit_override_can_modify_its_credit(self) -> None:
        self.branch.credit_override_enabled = True
        self.branch.save(update_fields=['credit_override_enabled', 'updated_at'])

        response = self.client.post(
            reverse('clients:edit_v2', args=[self.branch.pk]),
            data={
                'section': 'credit',
                'credit_policy-can_pay_with_credit': 'on',
                'credit_policy-credit_limit': '500.00',
                'credit_config-payment_term_type': 'monthly_cutoff',
                'credit_config-cutoff_day': 'last_day',
                'credit_config-max_payment_days': '30',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.credit_limit, Decimal('500.00'))

    def test_edit_page_links_to_client_detail(self) -> None:
        response = self.client.get(
            reverse('clients:edit_v2', args=[self.branch.pk]),
        )

        self.assertContains(
            response,
            reverse('clients:detail', args=[self.branch.pk]),
        )


class BranchCreditPatchTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='credit-patch-admin',
            password='testpass123',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)
        self.corporate = Client.objects.create(
            name='Corporativo patch crédito',
            type='corporate',
        )
        self.branch = Client.objects.create(
            name='Sucursal patch crédito',
            type='branch',
            corporate=self.corporate,
            credit_limit=Decimal('1000.00'),
            can_pay_with_credit=True,
        )

    def test_branch_without_credit_override_patch_rejects_credit_policy(self) -> None:
        response = self.client.patch(
            reverse('clients:update', args=[self.branch.pk]),
            data=json.dumps({
                'credit_limit': '500.00',
                'can_pay_with_credit': False,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.credit_limit, Decimal('1000.00'))
        self.assertTrue(self.branch.can_pay_with_credit)

    def test_branch_with_credit_override_patch_updates_credit_policy(self) -> None:
        self.branch.credit_override_enabled = True
        self.branch.save(update_fields=['credit_override_enabled', 'updated_at'])

        response = self.client.patch(
            reverse('clients:update', args=[self.branch.pk]),
            data=json.dumps({
                'credit_limit': '500.00',
                'can_pay_with_credit': False,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.credit_limit, Decimal('500.00'))
        self.assertFalse(self.branch.can_pay_with_credit)


class BranchCreditAdminTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='credit-admin-inline-user',
            password='testpass123',
            is_staff=True,
            is_superuser=True,
        )
        self.request = RequestFactory().get('/admin/clients/client/1/change/')
        self.request.user = self.user
        self.client_admin = ClientAdmin(Client, AdminSite())
        self.corporate = Client.objects.create(
            name='Corporativo admin crédito',
            type='corporate',
        )
        self.branch = Client.objects.create(
            name='Sucursal admin crédito',
            type='branch',
            corporate=self.corporate,
        )

    def _inline_types_for(self, client: Client) -> set[type]:
        return {
            type(inline)
            for inline in self.client_admin.get_inline_instances(self.request, client)
        }

    def test_branch_without_credit_override_hides_credit_config_inline(self) -> None:
        inline_types = self._inline_types_for(self.branch)

        self.assertNotIn(ClientCreditConfigInline, inline_types)

    def test_branch_with_credit_override_shows_credit_config_inline(self) -> None:
        self.branch.credit_override_enabled = True
        self.branch.save(update_fields=['credit_override_enabled', 'updated_at'])

        inline_types = self._inline_types_for(self.branch)

        self.assertIn(ClientCreditConfigInline, inline_types)


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


class ClientCreditDueDateDetailTests(FastTenantTestCase):
    def test_detail_context_contains_nearest_credit_due_date(self) -> None:
        user = User.objects.create_user(
            username='client-detail-user',
            password='testpass123',
        )
        client = Client.objects.create(
            name='Cliente con fecha de corte',
            type='corporate',
            credit_limit=Decimal('500.00'),
            can_pay_with_credit=True,
        )
        ClientCreditConfig.objects.create(
            client=client,
            payment_term_type='monthly_cutoff',
            cutoff_day='last_day',
        )
        order = Order.objects.create(
            client=client,
            total_amount=Decimal('100.00'),
            type='credito',
        )
        balance_service.add_debt(
            client=client,
            amount=Decimal('100.00'),
            transaction_type='purchase',
            reference_order=order,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('clients:detail', args=[client.pk]))

        today = timezone.localdate()
        expected_due_date = today.replace(
            day=monthrange(today.year, today.month)[1],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['pending_payment_data']['nearest_due_date'],
            expected_due_date,
        )
        self.assertContains(response, 'Ciclo de vencimiento')
        self.assertContains(response, 'Último día del mes')
        self.assertNotContains(response, 'Total Ventas')
        self.assertNotContains(response, 'Total Gastado')
