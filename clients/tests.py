from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.urls import reverse
from decimal import Decimal
from datetime import date, timedelta
import csv
import io
from tenant_client.test_utils import FastTenantTestCase
from .models import (
    Client, InvoiceData, Address, BalanceTransaction, CreditTransaction,
    Contact, ClientBillingFrecuency, ClientCreditConfig
)
from .forms import AddressInlineForm
from .services.csv_import_service import (
    _get_or_create_corporate,
    export_clients_to_csv,
    get_clients_csv_template,
    import_clients_from_csv,
)
from core.models import Transport
from orders.models import Order, OrderStatus
from payment.models import Payment
from routes.models import Route, RouteClient

User = get_user_model()


class ClientBillingInheritanceTestCase(FastTenantTestCase):
    """Business-rule focused tests for branch billing inheritance."""

    def setUp(self):
        self.corporate = Client.objects.create(
            name="Corporate Client",
            type="corporate",
            requires_billing=True,
            active=True,
        )
        InvoiceData.objects.create(
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

        self.branch_with_own_billing = Client.objects.create(
            name="Branch With Own Billing",
            type="branch",
            corporate=self.corporate,
            credit_override_enabled=True,
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
        InvoiceData.objects.create(
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
        InvoiceData.objects.create(
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

    def test_branch_always_uses_corporate_even_with_own_complete_data(self):
        InvoiceData.objects.create(
            client=self.branch_with_own_billing,
            rfc="BRANCH123456XYZ",
            razon_social="Sucursal SA de CV",
        )
        Address.objects.create(
            client=self.branch_with_own_billing,
            type="billing",
            street="Av. Sucursal 200",
            municipality="Querétaro",
            state="Querétaro",
            zip_code="76100",
            country="México",
            active=True,
        )
        ClientBillingFrecuency.objects.create(
            client=self.branch_with_own_billing,
            frequency="monthly",
            billing_date="last_day",
            is_active=True,
        )

        billing = self.branch_with_own_billing.billing_info
        self.assertTrue(billing.is_complete)
        self.assertEqual(billing.source, 'corporate')
        self.assertEqual(billing.effective.data, self.corporate.invoice_data)
        self.assertEqual(
            billing.effective.address,
            self.corporate.addresses.get(type='billing'),
        )
        self.assertEqual(billing.effective.frequency, self.corporate.invoice_schedule)

    def test_branch_ignores_incomplete_own_data_when_corporate_ready(self):
        InvoiceData.objects.create(
            client=self.branch_with_own_billing,
            rfc="PART123456",
            razon_social="Parcial SA",
        )

        billing = self.branch_with_own_billing.billing_info
        self.assertTrue(billing.is_complete)
        self.assertEqual(billing.source, 'corporate')
        self.assertEqual(billing.effective.data, self.corporate.invoice_data)


class AddressInlineFormTests(FastTenantTestCase):
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


class ClientDetailOrderActionsTests(FastTenantTestCase):
    def test_closed_order_still_shows_order_action_link(self) -> None:
        user = User.objects.create_user(
            username='client-detail-actions-user',
            password='testpass123',
        )
        customer = Client.objects.create(
            name='Cliente con pedido cerrado',
            active=True,
        )
        order = Order.objects.create(
            client=customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('100.00'),
        )
        Payment.objects.create(
            client=customer,
            order=order,
            amount=Decimal('100.00'),
            method='cash',
            status='completed',
            created_by=user,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('clients:detail', args=[customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("orders:get_order", args=[order.pk])}"',
        )


class ClientListModeTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='client_mode_user', password='testpass123')
        self.client.login(username='client_mode_user', password='testpass123')

    def _create_client(self, *, name: str, debt: Decimal = Decimal('0.00')) -> Client:
        client = Client.objects.create(
            name=name,
            current_debt=debt,
            active=True,
        )
        Address.objects.create(
            client=client,
            type='delivery',
            street=f'Calle {name}',
            active=True,
        )
        return client

    def test_credits_mode_filters_clients_with_debt(self) -> None:
        debt_client = self._create_client(name='Cliente con deuda', debt=Decimal('150.00'))
        self._create_client(name='Cliente sin deuda')

        response = self.client.get(reverse('clients:list'), {'mode': 'credits'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Créditos')
        self.assertContains(response, debt_client.name)
        self.assertContains(response, reverse('clients:pay_credit', kwargs={'pk': debt_client.pk}))
        self.assertNotContains(response, 'Cliente sin deuda')

    def test_outside_route_sales_mode_does_not_exclude_today_route_clients(self) -> None:
        route_client = self._create_client(name='Cliente en ruta')
        other_client = self._create_client(name='Cliente fuera de ruta')
        transport = Transport.objects.create(
            license_plate='OUT-001',
            model='Unidad venta',
            capacity_liters=1000,
            is_active=True,
        )
        today = date.today()
        route = Route.objects.create(
            name='Ruta de hoy',
            transportation=transport,
            weekday=today.strftime('%A').lower(),
            is_active=True,
        )
        RouteClient.objects.create(
            route=route,
            client=route_client,
            sequence=1,
            interval_weeks=1,
            anchor_date=today,
            is_active=True,
        )

        response = self.client.get(reverse('clients:list'), {'mode': 'outside_route_sales'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ventas fuera de ruta')
        self.assertContains(response, route_client.name)
        self.assertContains(response, other_client.name)

    def test_client_list_preserves_mode_in_search_and_pagination(self) -> None:
        for index in range(11):
            self._create_client(
                name=f'Credito paginado {index:02d}',
                debt=Decimal('25.00'),
            )

        response = self.client.get(
            reverse('clients:list'),
            {
                'mode': 'credits',
                'search': 'Credito paginado',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="mode" value="credits"')
        self.assertContains(response, 'mode=credits')
        self.assertContains(response, 'search=Credito+paginado')


class ClientRouteAssignmentTabTests(FastTenantTestCase):
    """Tests for managing RouteClient assignments from the client edit form."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='route_tab_admin',
            password='testpass123',
            is_staff=True,
        )
        self.client.login(username='route_tab_admin', password='testpass123')
        self.client_obj = Client.objects.create(
            name='Route Tab Client',
            type='corporate',
            active=True,
        )
        self.transport = Transport.objects.create(
            license_plate='TAB-001',
            model='Route Tab Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.active_route = Route.objects.create(
            name='Active Client Tab Route',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )
        self.inactive_route = Route.objects.create(
            name='Inactive Hidden Client Tab Route',
            transportation=self.transport,
            weekday='tuesday',
            is_active=False,
        )

    def _edit_url(self) -> str:
        return reverse('clients:edit_v2', kwargs={'pk': self.client_obj.pk})

    def _route_formset_post_data(self, route: Route) -> dict:
        return {
            'section': 'routes',
            'routes-TOTAL_FORMS': '1',
            'routes-INITIAL_FORMS': '0',
            'routes-MIN_NUM_FORMS': '0',
            'routes-MAX_NUM_FORMS': '1000',
            'routes-0-route': str(route.pk),
            'routes-0-sequence': '1',
            'routes-0-interval_weeks': '1',
            'routes-0-anchor_date': '2026-06-22',
            'routes-0-is_active': 'on',
            'routes-0-notes': 'Visita semanal',
        }

    def test_edit_form_renders_routes_tab(self) -> None:
        response = self.client.get(f'{self._edit_url()}?tab=routes')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rutas')
        self.assertContains(response, 'Asignaciones de Ruta')
        self.assertContains(response, 'Fecha de inicio de ciclo')
        self.assertNotContains(response, 'Anchor date')

    def test_route_select_only_offers_active_routes_for_new_assignment(self) -> None:
        response = self.client.get(f'{self._edit_url()}?tab=routes')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.active_route.name)
        self.assertNotContains(response, self.inactive_route.name)

    def test_post_valid_route_assignment_creates_route_client(self) -> None:
        Address.objects.create(
            client=self.client_obj,
            type='delivery',
            street='Calle Ruta 1',
            active=True,
        )

        response = self.client.post(
            self._edit_url(),
            data=self._route_formset_post_data(self.active_route),
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            RouteClient.objects.filter(
                client=self.client_obj,
                route=self.active_route,
                is_active=True,
            ).exists()
        )

    def test_missing_delivery_address_keeps_user_on_routes_tab_with_errors(self) -> None:
        response = self.client.post(
            self._edit_url(),
            data=self._route_formset_post_data(self.active_route),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dirección de envío válida')
        self.assertFalse(RouteClient.objects.filter(client=self.client_obj).exists())


class ClientCSVExternalIdTests(FastTenantTestCase):
    """Tests for CSV import/export support of client external_id."""

    def test_template_includes_external_id_header(self) -> None:
        template = get_clients_csv_template()
        header = template.splitlines()[0]
        self.assertIn("external_id", header)

    def test_import_sets_external_id(self) -> None:
        csv_content = (
            "client_name,external_id,type,corporate_name,active,note,address_street,"
            "address_exterior_number,address_interior_number,address_locality,address_municipality,"
            "address_state,address_zip_code,address_country,address_reference,contact_name,"
            "contact_phone,contact_email\n"
            "Cliente CSV,EXT-123,corporate,,true,nota,Av 1,10,,Centro,Queretaro,"
            "Queretaro,76000,Mexico,Referencia,Juan,5551234,juan@test.com\n"
        )

        summary = import_clients_from_csv(csv_content.encode("utf-8"))

        self.assertEqual(summary.created_clients, 1)
        client = Client.objects.get(name="Cliente CSV corporativo")
        self.assertEqual(client.external_id, "EXT-123")

    def test_export_includes_external_id_value(self) -> None:
        client = Client.objects.create(
            name="Cliente Export",
            type="corporate",
            active=True,
            external_id="ERP-900",
        )
        Address.objects.create(
            client=client,
            type="delivery",
            street="Calle Export 1",
            locality="Queretaro",
            municipality="Queretaro",
            state="Queretaro",
            zip_code="76000",
            country="Mexico",
            active=True,
        )

        exported = export_clients_to_csv([client])
        reader = csv.DictReader(io.StringIO(exported))
        rows = list(reader)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "ERP-900")


class ClientCSVCorporateNormalizationTests(FastTenantTestCase):
    def test_reuses_existing_corporate_without_suffix(self) -> None:
        existing = Client.objects.create(
            name="Michoacana",
            type="corporate",
            active=True,
        )

        corporate = _get_or_create_corporate("Michoacana")

        self.assertEqual(corporate.pk, existing.pk)
        corporate.refresh_from_db()
        self.assertEqual(corporate.name, "Michoacana corporativo")
        self.assertEqual(
            Client.objects.filter(
                type="corporate",
                name__in=["Michoacana", "Michoacana corporativo"],
            ).count(),
            1,
        )

    def test_import_uses_only_suffixed_corporate_name(self) -> None:
        csv_content = (
            "client_name,external_id,type,corporate_name,active,note,address_street,"
            "address_exterior_number,address_interior_number,address_locality,address_municipality,"
            "address_state,address_zip_code,address_country,address_reference,contact_name,"
            "contact_phone,contact_email\n"
            "BANANE,ERP-200,corporate,,true,,Av 10,10,,Centro,Queretaro,Queretaro,76000,Mexico,,,\n"
            "BANANE OLVERA,ERP-201,branch,BANANE,true,,Av 11,11,,Centro,Queretaro,Queretaro,76000,Mexico,,,\n"
        )

        summary = import_clients_from_csv(csv_content.encode("utf-8"))

        self.assertEqual(summary.errors, [])
        self.assertTrue(Client.objects.filter(name="BANANE OLVERA", type="branch").exists())
        self.assertTrue(Client.objects.filter(name="BANANE corporativo", type="corporate").exists())
        self.assertFalse(Client.objects.filter(name="BANANE", type="corporate").exists())
        self.assertEqual(Client.objects.filter(name__icontains="BANANE", type="corporate").count(), 1)
