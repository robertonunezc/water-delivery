from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from clients.models import Address, Client, Contact
from core.models import Transport
from tenant_client.test_utils import FastTenantTestCase

from .forms import RouteClientForm, RouteClientInlineForm
from .models import Route, RouteClient
from .services import get_route_detail_payload

User = get_user_model()


class RouteClientValidationTest(FastTenantTestCase):
    """Test client assignment validation and duplicate detection"""
    
    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(
            username='testadmin',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        # Create test clients
        self.client1 = Client.objects.create(name='Test Client 1')
        self.client2 = Client.objects.create(name='Test Client 2')

        Address.objects.create(client=self.client1, type='delivery', street='Calle 1')
        Address.objects.create(client=self.client2, type='delivery', street='Calle 2')
        
        # Create test transport
        self.transport = Transport.objects.create(
            license_plate='ABC-123',
            model='Test Vehicle',
            capacity_liters=1000,
            is_active=True
        )
        
        # Create test routes
        self.route1 = Route.objects.create(
            name='Route Monday',
            transportation=self.transport,
            weekday='monday',
            is_active=True
        )
        
        self.route2 = Route.objects.create(
            name='Route Tuesday',
            transportation=self.transport,
            weekday='tuesday',
            is_active=True
        )
        
        # Create initial assignment
        self.route_client1 = RouteClient.objects.create(
            route=self.route1,
            client=self.client1,
            sequence=1,
            is_active=True
        )
    
    def test_duplicate_client_assignment_validation(self):
        """Test that form validation catches duplicate client assignments"""
        form_data = {
            'client': self.client1.id,
            'sequence': 1,
            'interval_weeks': 1,
            'anchor_date': date.today(),
            'is_active': True,
            'notes': 'Test assignment'
        }
        
        # Create form for route2 with client1 (already assigned to route1)
        form = RouteClientInlineForm(data=form_data)
        form._formset = type('MockFormset', (), {'instance': self.route2})()
        
        self.assertFalse(form.is_valid())
        self.assertIn('client', form.errors)
        self.assertIn('CONFLICTO DE ASIGNACIÓN', str(form.errors['client']))
    
    def test_duplicate_client_assignment_with_confirmation(self):
        """Test that form accepts duplicate assignment with confirmation"""
        form_data = {
            'client': self.client1.id,
            'sequence': 1,
            'interval_weeks': 1,
            'anchor_date': date.today(),
            'is_active': True,
            'notes': 'Test assignment',
            'confirm_duplicate_assignment': True
        }
        
        # Use inline form with confirmation
        form = RouteClientInlineForm(data=form_data)
        form._formset = type('MockFormset', (), {'instance': self.route2})()
        
        self.assertTrue(form.is_valid())
    
    def test_no_duplicate_for_same_route(self):
        """Test that no validation error occurs when editing existing assignment"""
        form_data = {
            'client': self.client1.id,
            'sequence': 1,
            'interval_weeks': 1,
            'anchor_date': date.today(),
            'is_active': True,
            'notes': 'Updated notes'
        }
        
        # Edit existing assignment
        form = RouteClientForm(data=form_data, instance=self.route_client1)
        
        self.assertTrue(form.is_valid())
    
    def test_no_duplicate_for_different_client(self):
        """Test that no validation error occurs for different client"""
        form_data = {
            'client': self.client2.id,
            'sequence': 2,
            'interval_weeks': 1,
            'anchor_date': date.today(),
            'is_active': True,
            'notes': 'New client assignment'
        }
        
        form = RouteClientForm(data=form_data)
        form._formset = type('MockFormset', (), {'instance': self.route1})()
        
        self.assertTrue(form.is_valid())
    
    def test_check_client_assignments_ajax_view(self):
        """Test the AJAX endpoint for checking client assignments"""
        self.client_test = self.client
        self.client_test.login(username='testadmin', password='testpass123')
        
        # Test with existing assignment
        response = self.client_test.get(
            reverse('routes:check_client_assignments'),
            {
                'client_id': self.client1.id,
                'current_route_id': self.route2.id
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['has_conflicts'])
        self.assertIn('Route Monday', data['existing_routes'][0])
    
    def test_check_client_assignments_no_conflict(self):
        """Test AJAX endpoint with no conflicts"""
        self.client_test = self.client
        self.client_test.login(username='testadmin', password='testpass123')
        
        # Test with client that has no assignments
        response = self.client_test.get(
            reverse('routes:check_client_assignments'),
            {
                'client_id': self.client2.id,
                'current_route_id': self.route1.id
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['has_conflicts'])
    
    def test_check_client_assignments_requires_staff(self):
        """Test that AJAX endpoint requires staff access"""
        # Create non-staff user
        regular_user = User.objects.create_user(
            username='regular',
            password='testpass123',
            is_staff=False
        )
        
        self.client_test = self.client
        self.client_test.login(username='regular', password='testpass123')
        
        response = self.client_test.get(
            reverse('routes:check_client_assignments'),
            {'client_id': self.client1.id}
        )
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])


class RouteClientFrequencyIntervalTest(FastTenantTestCase):
    def setUp(self):
        self.delivery_client = Client.objects.create(name='Frequency Client')
        Address.objects.create(client=self.delivery_client, type='delivery', street='Calle Frecuencia')
        self.transport = Transport.objects.create(
            license_plate='XYZ-999',
            model='Test Vehicle',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Route Monday',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )

    def test_is_due_on_every_two_weeks(self):
        route_client = RouteClient.objects.create(
            route=self.route,
            client=self.delivery_client,
            sequence=1,
            interval_weeks=2,
            anchor_date=date(2026, 3, 2),  # Monday
            is_active=True,
        )

        self.assertTrue(route_client.is_due_on(date(2026, 3, 2)))
        self.assertFalse(route_client.is_due_on(date(2026, 3, 9)))
        self.assertTrue(route_client.is_due_on(date(2026, 3, 16)))

    def test_due_on_queryset_filters_clients(self):
        RouteClient.objects.create(
            route=self.route,
            client=self.delivery_client,
            sequence=1,
            interval_weeks=1,
            anchor_date=date(2026, 3, 2),
            is_active=True,
        )

        second_client = Client.objects.create(name='Every 2 Weeks')
        Address.objects.create(client=second_client, type='delivery', street='Calle 2 semanas')
        RouteClient.objects.create(
            route=self.route,
            client=second_client,
            sequence=2,
            interval_weeks=2,
            anchor_date=date(2026, 3, 2),
            is_active=True,
        )

        due_first_week = RouteClient.objects.due_on(date(2026, 3, 2))
        due_second_week = RouteClient.objects.due_on(date(2026, 3, 9))

        self.assertEqual(due_first_week.count(), 2)
        self.assertEqual(due_second_week.count(), 1)


class RouteDashboardSummaryServiceTest(FastTenantTestCase):
    def setUp(self):
        self.transport = Transport.objects.create(
            license_plate='SUM-001',
            model='Summary Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.monday_route = Route.objects.create(
            name='Summary Monday',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )
        self.tuesday_route = Route.objects.create(
            name='Summary Tuesday',
            transportation=self.transport,
            weekday='tuesday',
            is_active=True,
        )

    def _create_route_client(
        self,
        *,
        name: str,
        route: Route,
        sequence: int,
        interval_weeks: int = 1,
        is_active: bool = True,
    ) -> RouteClient:
        client = Client.objects.create(name=name)
        Address.objects.create(client=client, type='delivery', street=f'Calle {name}')
        return RouteClient.objects.create(
            route=route,
            client=client,
            sequence=sequence,
            interval_weeks=interval_weeks,
            anchor_date=date(2026, 3, 2),
            is_active=is_active,
        )

    def test_get_route_clients_due_count_uses_due_on_queryset(self):
        from routes.services import get_route_clients_due_count

        self._create_route_client(name='Due Every Week', route=self.monday_route, sequence=1)
        self._create_route_client(
            name='Not Due This Week',
            route=self.monday_route,
            sequence=2,
            interval_weeks=2,
        )
        self._create_route_client(
            name='Inactive Client',
            route=self.monday_route,
            sequence=3,
            is_active=False,
        )
        self._create_route_client(name='Different Weekday', route=self.tuesday_route, sequence=4)

        count = get_route_clients_due_count(date(2026, 3, 9))

        self.assertEqual(count, 1)


class RouteDetailRefactorTest(FastTenantTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='route_user',
            password='testpass123',
            is_staff=True,
        )
        self.transport = Transport.objects.create(
            license_plate='RTE-001',
            model='Test Truck',
            capacity_liters=800,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Route Search',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )

        self.client_match = Client.objects.create(name='Alpha Water')
        Address.objects.create(
            client=self.client_match,
            type='delivery',
            street='Calle Norte',
            locality='Centro',
            zip_code='76010',
        )
        Contact.objects.create(
            client=self.client_match,
            name='Ana',
            phone='5551112222',
        )
        self.route_client_match = RouteClient.objects.create(
            route=self.route,
            client=self.client_match,
            sequence=1,
            is_active=True,
        )

        self.client_other = Client.objects.create(name='Beta Water')
        Address.objects.create(
            client=self.client_other,
            type='delivery',
            street='Calle Sur',
        )
        self.route_client_other = RouteClient.objects.create(
            route=self.route,
            client=self.client_other,
            sequence=2,
            is_active=True,
        )

    def test_get_route_detail_payload_filters_and_prefetches(self):
        payload = get_route_detail_payload(route=self.route, search_query='Ana')
        route_clients = list(payload.route_clients)

        self.assertEqual(len(route_clients), 1)
        self.assertEqual(route_clients[0].id, self.route_client_match.id)
        self.assertEqual(payload.search_query, 'Ana')
        self.assertFalse(payload.is_today_view)
        self.assertEqual(payload.today, date.today())
        self.assertTrue(hasattr(route_clients[0].client, 'recent_orders'))

    def test_route_detail_view_uses_service_payload_with_search(self):
        client = self.client
        client.login(username='route_user', password='testpass123')

        response = client.get(
            reverse('routes:detail', kwargs={'route_id': self.route.id}),
            {'q': 'Norte'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'routes/route_detail.html')
        self.assertEqual(response.context['search_query'], 'Norte')
        self.assertEqual(len(response.context['route_clients']), 1)
        self.assertEqual(response.context['route_clients'][0].id, self.route_client_match.id)
