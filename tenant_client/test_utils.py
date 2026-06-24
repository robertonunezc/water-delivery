"""
Test utilities for multi-tenant testing.

Provides mixins and helper functions for creating and managing test tenants
in unit and integration tests.
"""
from datetime import date, timedelta
from django_tenants.test.cases import FastTenantTestCase as DjangoTenantsFastTenantTestCase
from django_tenants.test.client import TenantClient
from .models import ClientTenant, Domain


class TenantTestMixin:
    """
    Mixin for creating test tenants in unit tests.

    Use this mixin in your test classes to easily create isolated tenant
    environments for testing tenant-specific functionality.

    Example:
        class MyTenantTest(TenantTestMixin, TestCase):
            def setUp(self):
                self.tenant, self.domain = self.setup_test_tenant()

            def test_something(self):
                # Test runs in context of test tenant
                pass
    """

    @classmethod
    def setup_test_tenant(
        cls,
        schema_name: str = 'test',
        domain_name: str = 'test.localhost',
        name: str = None,
        paid_until: date = None,
        on_trial: bool = False
    ):
        """
        Create a test tenant with domain.

        Args:
            schema_name: PostgreSQL schema name (default: 'test')
            domain_name: Domain for tenant (default: 'test.localhost')
            name: Display name (default: 'Test Tenant {schema_name}')
            paid_until: Subscription expiry (default: 1 year from now)
            on_trial: Trial status (default: False)

        Returns:
            Tuple of (ClientTenant, Domain)

        Example:
            >>> tenant, domain = self.setup_test_tenant(
            ...     schema_name='acme_test',
            ...     domain_name='acme.test.localhost',
            ...     name='Acme Test Corp'
            ... )
        """
        if name is None:
            name = f'Test Tenant {schema_name}'

        if paid_until is None:
            paid_until = date.today() + timedelta(days=365)

        tenant = ClientTenant.objects.create(
            schema_name=schema_name,
            name=name,
            paid_until=paid_until,
            on_trial=on_trial
        )

        domain = Domain.objects.create(
            domain=domain_name,
            tenant=tenant,
            is_primary=True
        )

        return tenant, domain

    @classmethod
    def teardown_test_tenant(cls, tenant: ClientTenant):
        """
        Delete a test tenant and its schema.

        Args:
            tenant: ClientTenant instance to delete

        Example:
            >>> self.teardown_test_tenant(self.tenant)
        """
        # Delete tenant (cascade deletes domains and drops schema)
        tenant.delete()


class FastTenantTestCase(DjangoTenantsFastTenantTestCase):
    """
    Base test case for tenant-specific tests.

    This class extends django-tenants' FastTenantTestCase so tenant-aware
    suites reuse the framework's fast test schema behavior instead of
    recreating the fixed ``test`` tenant for each test class.

    Example:
        class ClientModelTest(FastTenantTestCase):
            @classmethod
            def setup_tenant(cls, tenant):
                # Add test data to tenant
                return tenant

            def test_client_creation(self):
                # Test runs in tenant schema context
                pass
    """

    @classmethod
    def setup_tenant(cls, tenant):
        """
        Populate the required fields on the tenant model used by tests.

        django-tenants instantiates the tenant with only ``schema_name`` by
        default. Our ClientTenant model requires extra non-null fields, so the
        shared test base must provide safe defaults for suites that don't
        override ``setup_tenant()`` themselves.
        """
        tenant.name = tenant.name or f"Test Tenant {tenant.schema_name}"
        tenant.paid_until = tenant.paid_until or (date.today() + timedelta(days=30))
        tenant.on_trial = tenant.on_trial if tenant.on_trial is not None else False
        return tenant

    @classmethod
    def setup_test_data(cls):
        """
        Override this method to add test data to the tenant.

        Called after tenant creation but before tests run.
        """
        pass


def create_public_tenant():
    """
    Create the public tenant for testing.

    This should be called once in test setup to ensure the public
    schema exists before creating other tenants.

    Returns:
        Tuple of (ClientTenant, Domain)

    Example:
        >>> from tenant_client.test_utils import create_public_tenant
        >>> public_tenant, public_domain = create_public_tenant()
    """
    try:
        # Check if public tenant already exists
        tenant = ClientTenant.objects.get(schema_name='public')
        domain = Domain.objects.filter(tenant=tenant).first()
        return tenant, domain
    except ClientTenant.DoesNotExist:
        # Create public tenant
        tenant = ClientTenant.objects.create(
            schema_name='public',
            name='Public Schema',
            paid_until=date.today() + timedelta(days=3650),  # 10 years
            on_trial=False
        )

        domain = Domain.objects.create(
            domain='localhost',  # Use localhost for testing
            tenant=tenant,
            is_primary=True
        )

        return tenant, domain


def get_tenant_client(tenant: ClientTenant):
    """
    Get a Django test client configured for a specific tenant.

    Args:
        tenant: ClientTenant instance

    Returns:
        TenantClient: Test client that operates in tenant's schema context

    Example:
        >>> tenant = ClientTenant.objects.get(schema_name='acme')
        >>> client = get_tenant_client(tenant)
        >>> response = client.get('/clients/')
    """
    return TenantClient(tenant)


def switch_tenant_context(tenant: ClientTenant):
    """
    Context manager for switching tenant context in tests.

    Args:
        tenant: ClientTenant to switch to

    Example:
        >>> from django_tenants.utils import schema_context
        >>> tenant1 = ClientTenant.objects.get(schema_name='tenant1')
        >>> tenant2 = ClientTenant.objects.get(schema_name='tenant2')
        >>>
        >>> with schema_context(tenant1.schema_name):
        ...     # Create data in tenant1
        ...     client = Client.objects.create(name='Tenant 1 Client')
        >>>
        >>> with schema_context(tenant2.schema_name):
        ...     # Verify data isolation - should return 0
        ...     count = Client.objects.count()
    """
    from django_tenants.utils import schema_context
    return schema_context(tenant.schema_name)
