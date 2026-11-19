from django.contrib.auth import get_user_model
from django.urls import reverse

from clients.models import Client, ClientCreditConfig
from tenant_client.test_utils import FastTenantTestCase


class ClientEditPersistenceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username='client-editor', password='test',
        )
        self.client.force_login(self.user)
        self.customer = Client.objects.create(
            name='Cliente original', type='corporate', requires_billing=True,
        )

    def _basic_data(self) -> dict[str, str]:
        return {
            'section': 'basic',
            'name': 'Cliente actualizado',
            'type': 'corporate',
            'active': 'on',
            'external_id': 'ERP-123',
            'address_link': 'https://maps.google.com/example',
            'confirmation_delivery_method': 'email',
            'note': 'Notas actualizadas',
        }

    def test_basic_edit_persists_visible_fields_without_disabling_billing(self) -> None:
        response = self.client.post(
            reverse('admin_edit_client', args=[self.customer.pk]), self._basic_data(),
        )

        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, 'Cliente actualizado')
        self.assertEqual(self.customer.external_id, 'ERP-123')
        self.assertEqual(self.customer.address_link, 'https://maps.google.com/example')
        self.assertEqual(self.customer.confirmation_delivery_method, 'email')
        self.assertEqual(self.customer.note, 'Notas actualizadas')
        self.assertTrue(self.customer.requires_billing)

    def test_basic_edit_saves_when_credit_depends_on_invoicing(self) -> None:
        ClientCreditConfig.objects.create(
            client=self.customer, payment_term_type='invoice_due', max_payment_days=15,
        )

        response = self.client.post(
            reverse('clients:edit_v2', args=[self.customer.pk]), self._basic_data(),
        )

        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, 'Cliente actualizado')
        self.assertTrue(self.customer.requires_billing)

    def test_invalid_basic_edit_keeps_persisted_data_and_shows_error(self) -> None:
        response = self.client.post(
            reverse('admin_edit_client', args=[self.customer.pk]),
            {**self._basic_data(), 'name': ''},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('name', response.context['core_form'].errors)
        self.assertContains(response, response.context['core_form'].errors['name'][0])
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, 'Cliente original')
        self.assertTrue(self.customer.requires_billing)

    def test_recurring_billing_tab_can_still_disable_billing(self) -> None:
        response = self.client.post(
            reverse('admin_edit_client', args=[self.customer.pk]),
            {'section': 'recurring_billing'},
        )

        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.requires_billing)
