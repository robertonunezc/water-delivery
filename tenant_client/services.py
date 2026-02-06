"""
Service layer for tenant management operations.

Provides functions for creating, updating, and managing tenants and domains.
"""
from typing import Tuple
from datetime import date
from django.db import transaction
from .models import ClientTenant, Domain
import logging

logger = logging.getLogger(__name__)


@transaction.atomic
def create_tenant_with_domain(
    name: str,
    schema_name: str,
    domain_name: str,
    paid_until: date,
    on_trial: bool = False
) -> Tuple[ClientTenant, Domain]:
    """
    Create a new tenant with associated domain.

    This function atomically creates both a tenant and its primary domain,
    ensuring data consistency. The tenant's PostgreSQL schema is automatically
    created when auto_create_schema=True is set on the ClientTenant model.

    Args:
        name: Display name for tenant (e.g., "Acme Corporation")
        schema_name: PostgreSQL schema name (alphanumeric + underscore only, e.g., "acme_corp")
        domain_name: Full domain (e.g., "acme.yourdomain.com")
        paid_until: Subscription expiry date
        on_trial: Whether tenant is on trial period (default: False)

    Returns:
        Tuple of (ClientTenant, Domain)

    Raises:
        ValueError: If schema_name contains invalid characters
        django.db.IntegrityError: If schema_name or domain_name already exists

    Example:
        >>> from datetime import date, timedelta
        >>> tenant, domain = create_tenant_with_domain(
        ...     name="Acme Corp",
        ...     schema_name="acme_corp",
        ...     domain_name="acme.yourdomain.com",
        ...     paid_until=date.today() + timedelta(days=365),
        ...     on_trial=True
        ... )
        >>> print(f"Created tenant: {tenant.name} at {domain.domain}")
    """
    # Validate schema_name (PostgreSQL schema naming rules)
    if not schema_name.replace('_', '').isalnum():
        raise ValueError(
            f"schema_name '{schema_name}' must be alphanumeric with underscores only. "
            "No spaces, hyphens, or special characters allowed."
        )

    # Reserved schema names that should not be used
    reserved_schemas = {'public', 'information_schema', 'pg_catalog', 'pg_toast'}
    if schema_name.lower() in reserved_schemas:
        raise ValueError(
            f"schema_name '{schema_name}' is a reserved PostgreSQL schema name. "
            f"Reserved names: {', '.join(reserved_schemas)}"
        )

    # Create tenant (auto_create_schema=True creates PostgreSQL schema automatically)
    tenant = ClientTenant.objects.create(
        name=name,
        schema_name=schema_name,
        paid_until=paid_until,
        on_trial=on_trial
    )

    # Create primary domain
    domain = Domain.objects.create(
        domain=domain_name,
        tenant=tenant,
        is_primary=True
    )

    logger.info(
        f"Created tenant '{name}' with schema '{schema_name}' and domain '{domain_name}'",
        extra={
            'tenant_id': tenant.id,
            'schema_name': schema_name,
            'domain': domain_name,
            'on_trial': on_trial
        }
    )

    return tenant, domain


@transaction.atomic
def add_domain_to_tenant(tenant: ClientTenant, domain_name: str, is_primary: bool = False) -> Domain:
    """
    Add an additional domain to an existing tenant.

    Useful for adding alternative domains (e.g., custom domains) to a tenant.
    If is_primary=True and the tenant already has a primary domain, the existing
    primary will be set to non-primary.

    Args:
        tenant: ClientTenant instance
        domain_name: Domain to add (e.g., "custom.example.com")
        is_primary: Whether this should be the primary domain (default: False)

    Returns:
        Domain: The created Domain instance

    Example:
        >>> tenant = ClientTenant.objects.get(schema_name="acme_corp")
        >>> domain = add_domain_to_tenant(tenant, "custom.acme.com", is_primary=True)
    """
    if is_primary:
        # Set existing primary domains to non-primary
        Domain.objects.filter(tenant=tenant, is_primary=True).update(is_primary=False)

    domain = Domain.objects.create(
        domain=domain_name,
        tenant=tenant,
        is_primary=is_primary
    )

    logger.info(
        f"Added domain '{domain_name}' to tenant '{tenant.name}'",
        extra={
            'tenant_id': tenant.id,
            'schema_name': tenant.schema_name,
            'domain': domain_name,
            'is_primary': is_primary
        }
    )

    return domain


def get_tenant_by_domain(domain_name: str) -> ClientTenant:
    """
    Retrieve a tenant by its domain name.

    Args:
        domain_name: Domain to lookup (e.g., "acme.yourdomain.com")

    Returns:
        ClientTenant: The tenant associated with this domain

    Raises:
        Domain.DoesNotExist: If domain not found

    Example:
        >>> tenant = get_tenant_by_domain("acme.yourdomain.com")
        >>> print(tenant.name)
    """
    domain = Domain.objects.select_related('tenant').get(domain=domain_name)
    return domain.tenant


def extend_tenant_subscription(tenant: ClientTenant, days: int) -> ClientTenant:
    """
    Extend a tenant's subscription by a number of days.

    Args:
        tenant: ClientTenant instance
        days: Number of days to extend (positive integer)

    Returns:
        ClientTenant: Updated tenant instance

    Example:
        >>> tenant = ClientTenant.objects.get(schema_name="acme_corp")
        >>> tenant = extend_tenant_subscription(tenant, 365)
        >>> print(f"New expiry: {tenant.paid_until}")
    """
    from datetime import timedelta

    if days <= 0:
        raise ValueError("days must be a positive integer")

    tenant.paid_until = tenant.paid_until + timedelta(days=days)
    tenant.save(update_fields=['paid_until'])

    logger.info(
        f"Extended tenant '{tenant.name}' subscription by {days} days",
        extra={
            'tenant_id': tenant.id,
            'schema_name': tenant.schema_name,
            'new_expiry': tenant.paid_until.isoformat()
        }
    )

    return tenant
