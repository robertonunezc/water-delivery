from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from clients.models import Address, Client, InvoiceData
from invoice.forms import InvoiceCreateForm, InvoiceDraftEditForm
from invoice.models import Invoice
from invoice.services import create_invoice_from_orders, create_invoice_with_orders
from orders.models import Order
from payment.models import Payment
from tenant_client.test_utils import FastTenantTestCase


class InvoiceFiscalDataTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.owner = Client.objects.create(name='Corporativo Fiscal', type='corporate')
        self.fiscal_data = InvoiceData.objects.create(
            client=self.owner, rfc='CFS010101AAA',
            razon_social='Corporativo Fiscal SA de CV', curp='TEST010101HQTRRS01',
        )
        self.address = Address.objects.create(
            client=self.owner, type='billing', street='Fiscal', exterior_number='123',
            interior_number='4', locality='Centro', municipality='Querétaro',
            state='Querétaro', zip_code='76000', country='México',
        )
        self.order = Order.objects.create(
            client=self.owner, total_amount=Decimal('50.00'), status='COMPLETED',
        )
        Payment.objects.create(
            client=self.owner, order=self.order, amount=Decimal('50.00'),
            method='cash', status='completed',
        )
        self.staff = get_user_model().objects.create_user(
            username='invoice-staff', is_staff=True,
        )
        self.client.force_login(self.staff)

    def _form_data(self, **overrides: str) -> dict:
        data = {
            'client': str(self.owner.pk), 'identifier': 'FISCAL', 'folio': '1',
            'amount': '50.00', 'orders': [str(self.order.pk)],
            'rfc': 'EDIT010101AAA', 'razon_social': 'Receptor de la factura',
            'curp': '', 'billing_address': 'Domicilio específico de la factura',
        }
        data.update(overrides)
        return data

    def test_creation_form_prefills_customer_fiscal_data(self) -> None:
        form = InvoiceCreateForm(initial={'client': self.owner.pk})

        self.assertIn('rfc', form.fields)
        self.assertEqual(form['rfc'].value(), 'CFS010101AAA')
        self.assertEqual(form['razon_social'].value(), 'Corporativo Fiscal SA de CV')
        self.assertEqual(form['curp'].value(), 'TEST010101HQTRRS01')
        self.assertEqual(
            form['billing_address'].value(),
            'Fiscal 123 Int. 4, Centro, Querétaro, Querétaro, 76000, México',
        )
        self.assertIn(self.order, form.fields['orders'].queryset)

    def test_creation_page_prefills_client_from_query_string(self) -> None:
        response = self.client.get(reverse('admin_create_invoice'), {'client': self.owner.pk})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="CFS010101AAA"')
        self.assertContains(response, 'Corporativo Fiscal SA de CV')
        self.assertContains(response, 'invoice/js/invoice_fiscal_data.js', count=1)

    def test_branch_prefills_corporate_fiscal_data(self) -> None:
        branch = Client.objects.create(name='Sucursal', type='branch', corporate=self.owner)
        InvoiceData.objects.create(client=branch, rfc='WRONG', razon_social='Datos propios')

        form = InvoiceCreateForm(initial={'client': branch})

        self.assertIn('rfc', form.fields)
        self.assertEqual(form['rfc'].value(), 'CFS010101AAA')
        self.assertEqual(form['razon_social'].value(), 'Corporativo Fiscal SA de CV')

    def test_manual_creation_saves_edited_fiscal_data_without_changing_customer(self) -> None:
        response = self.client.post(reverse('admin_create_invoice'), self._form_data())

        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(identifier='FISCAL')
        self.assertEqual(getattr(invoice, 'rfc', None), 'EDIT010101AAA')
        self.assertEqual(invoice.razon_social, 'Receptor de la factura')
        self.assertEqual(invoice.curp, '')
        self.assertEqual(invoice.billing_address, 'Domicilio específico de la factura')
        self.fiscal_data.refresh_from_db()
        self.assertEqual(self.fiscal_data.rfc, 'CFS010101AAA')

    def test_invalid_submission_keeps_entered_fiscal_data(self) -> None:
        form = InvoiceCreateForm(data=self._form_data(identifier=''))

        self.assertFalse(form.is_valid())
        self.assertIn('rfc', form.fields)
        self.assertEqual(form['rfc'].value(), 'EDIT010101AAA')
        self.assertEqual(form['billing_address'].value(), 'Domicilio específico de la factura')

    def test_selected_orders_draft_keeps_fiscal_data_after_customer_changes(self) -> None:
        invoice = create_invoice_from_orders(orders=[self.order], client=self.owner)
        self.fiscal_data.rfc = 'NEW010101AAA'
        self.fiscal_data.save()
        self.address.street = 'Domicilio nuevo'
        self.address.save()
        invoice.refresh_from_db()

        self.assertEqual(getattr(invoice, 'rfc', None), 'CFS010101AAA')
        form = InvoiceDraftEditForm(instance=invoice)
        self.assertEqual(form['rfc'].value(), 'CFS010101AAA')
        self.assertIn('Fiscal 123 Int. 4', form['billing_address'].value())

    def test_manual_service_copies_fiscal_data_when_not_supplied(self) -> None:
        invoice = create_invoice_with_orders(
            invoice=Invoice(client=self.owner, amount=Decimal('50.00'), identifier='AUTO', folio='1'),
            orders=[self.order],
        )
        invoice.refresh_from_db()

        self.assertEqual(getattr(invoice, 'rfc', None), 'CFS010101AAA')

    def test_issuing_draft_saves_fiscal_edits_and_displays_saved_recipient(self) -> None:
        draft = create_invoice_from_orders(orders=[self.order], client=self.owner)
        response = self.client.post(reverse('admin_edit_invoice', args=[draft.pk]), self._form_data())

        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(getattr(draft, 'rfc', None), 'EDIT010101AAA')
        self.assertEqual(draft.status, 'ACTIVE')
        self.fiscal_data.rfc = 'NEW010101AAA'
        self.fiscal_data.save()
        detail = self.client.get(reverse('admin_edit_invoice', args=[draft.pk]))
        self.assertContains(detail, 'EDIT010101AAA')
        self.assertContains(detail, 'Receptor de la factura')
        self.assertNotContains(detail, 'NEW010101AAA')

    def test_issued_invoice_fiscal_data_is_immutable(self) -> None:
        invoice = create_invoice_with_orders(
            invoice=Invoice(client=self.owner, amount=Decimal('50.00'), identifier='LOCK', folio='1'),
            orders=[self.order],
        )
        invoice.rfc = 'CHANGED'

        with self.assertRaisesMessage(ValidationError, 'no se puede editar'):
            invoice.save()

    def test_fiscal_data_endpoint_returns_corporate_recipient_for_branch(self) -> None:
        branch = Client.objects.create(name='Sucursal', type='branch', corporate=self.owner)
        response = self.client.get(reverse('invoice:client_fiscal_data', args=[branch.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fiscal_data']['rfc'], 'CFS010101AAA')
        self.assertIn('Fiscal 123 Int. 4', response.json()['fiscal_data']['billing_address'])

    def test_fiscal_data_endpoint_requires_staff(self) -> None:
        self.staff.is_staff = False
        self.staff.save(update_fields=['is_staff'])

        response = self.client.get(reverse('invoice:client_fiscal_data', args=[self.owner.pk]))

        self.assertEqual(response.status_code, 302)

    def test_fiscal_data_endpoint_returns_blanks_for_missing_setup(self) -> None:
        owner = Client.objects.create(name='Sin datos', type='corporate')
        response = self.client.get(reverse('invoice:client_fiscal_data', args=[owner.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fiscal_data'], {
            'rfc': '', 'razon_social': '', 'curp': '', 'billing_address': '',
        })

    def test_orphan_branch_returns_validation_error_instead_of_crashing_form(self) -> None:
        branch = Client.objects.create(name='Sin corporativo', type='branch')

        form = InvoiceCreateForm(data=self._form_data(client=str(branch.pk)))

        self.assertFalse(form.is_valid())
        self.assertIn('client', form.errors)

    def test_legacy_draft_prefills_current_customer_data_before_issuing(self) -> None:
        draft = Invoice.objects.create(
            client=self.owner, amount=Decimal('50.00'), identifier='LEGACY',
            folio='1', status='DRAFT',
        )

        form = InvoiceDraftEditForm(instance=draft)

        self.assertEqual(form['rfc'].value(), 'CFS010101AAA')
        self.assertIn('Fiscal 123 Int. 4', form['billing_address'].value())

    def test_fiscal_data_endpoint_ignores_soft_deleted_fiscal_data(self) -> None:
        self.fiscal_data.delete()

        response = self.client.get(reverse('invoice:client_fiscal_data', args=[self.owner.pk]))

        self.assertEqual(response.json()['fiscal_data']['rfc'], '')

    def test_invoice_requires_fiscal_recipient_before_issuing(self) -> None:
        response = self.client.post(reverse('admin_create_invoice'), self._form_data(rfc=''))

        self.assertEqual(response.status_code, 200)
        self.assertIn('rfc', response.context['form'].errors)
        self.assertFalse(Invoice.objects.filter(identifier='FISCAL').exists())

    def test_native_admin_prefills_customer_fiscal_data(self) -> None:
        self.staff.is_superuser = True
        self.staff.save(update_fields=['is_superuser'])

        response = self.client.get(reverse('admin:billing_invoice_add'), {'client': self.owner.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['adminform'].form['rfc'].value(), 'CFS010101AAA')
        self.assertContains(response, 'invoice/js/invoice_fiscal_data.js', count=1)
        self.assertTrue('data-ajax--url=' in response.content.decode(), 'Debe conservar el selector con búsqueda de clientes.')

    def test_native_admin_rejects_incomplete_fiscal_recipient(self) -> None:
        from django.contrib import admin
        from django.test import RequestFactory

        request = RequestFactory().get('/admin/billing/invoice/add/')
        request.user = self.staff
        form_class = admin.site._registry[Invoice].get_form(request)
        form = form_class(data=self._form_data(razon_social='', billing_address=''))

        self.assertFalse(form.is_valid())
        self.assertIn('razon_social', form.errors)
        self.assertIn('billing_address', form.errors)
