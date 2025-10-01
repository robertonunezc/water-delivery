from django.test import TestCase, Client as TestClient
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.urls import reverse
from datetime import date
from .models import Route, RouteClient
from .forms import RouteClientForm, RouteClientInlineForm
from clients.models import Client
from core.models import Transport


class RouteClientValidationTest(TestCase):
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
        
        # Create test transport
        self.transport = Transport.objects.create(
            license_plate='ABC-123',
            model='Test Vehicle',
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
            'frequency': 'weekly',
            'is_active': True,
            'notes': 'Test assignment'
        }
        
        # Create form for route2 with client1 (already assigned to route1)
        form = RouteClientForm(data=form_data)
        form._formset = type('MockFormset', (), {'instance': self.route2})()
        
        self.assertFalse(form.is_valid())
        self.assertIn('client', form.errors)
        self.assertIn('ya está asignado', str(form.errors['client']))
    
    def test_duplicate_client_assignment_with_confirmation(self):
        """Test that form accepts duplicate assignment with confirmation"""
        form_data = {
            'client': self.client1.id,
            'sequence': 1,
            'frequency': 'weekly',
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
            'frequency': 'weekly',
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
            'frequency': 'weekly',
            'is_active': True,
            'notes': 'New client assignment'
        }
        
        form = RouteClientForm(data=form_data)
        form._formset = type('MockFormset', (), {'instance': self.route1})()
        
        self.assertTrue(form.is_valid())
    
    def test_check_client_assignments_ajax_view(self):
        """Test the AJAX endpoint for checking client assignments"""
        self.client_test = TestClient()
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
        self.client_test = TestClient()
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
        
        self.client_test = TestClient()
        self.client_test.login(username='regular', password='testpass123')
        
        response = self.client_test.get(
            reverse('routes:check_client_assignments'),
            {'client_id': self.client1.id}
        )
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
