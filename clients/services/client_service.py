from datetime import date
from invoice import services as invoice_service


def get_upcoming_route_orders(client, limit=10):
    """
    Get upcoming route client orders (specific deliveries) for a client.

    Args:
        client: Client instance
        limit: Maximum number of results to return (default: 10)

    Returns:
        QuerySet of upcoming RouteClientOrder instances
    """
    today = date.today()
    return client.client_route_orders.filter(
        visit_date__gte=today,
        is_completed=False
    ).select_related(
        'route__transportation__assigned_driver__user',
        'route',
        'order'
    ).order_by('visit_date')[:limit]

def get_all_clients():
    return Client.objects.all().filter(active=True)

def get_recent_completed_route_orders(client, limit=5):
    """
    Get recent completed route orders for a client.

    Args:
        client: Client instance
        limit: Maximum number of results to return (default: 5)

    Returns:
        QuerySet of recently completed RouteClientOrder instances
    """
    return client.client_route_orders.filter(
        is_completed=True
    ).select_related(
        'route__transportation__assigned_driver__user',
        'route',
        'order'
    ).order_by('-completed_at')[:limit]


from dataclasses import dataclass
from typing import Optional
from decimal import Decimal
from django.contrib.auth.models import User
from clients.models import Client


@dataclass
class ClientUpdateData:
    """Dataclass for client update information"""
    name: Optional[str] = None
    active: Optional[bool] = None
    note: Optional[str] = None
    type: Optional[str] = None
    corporate_id: Optional[int] = None
    balance: Optional[Decimal] = None
    credit_limit: Optional[Decimal] = None
    current_debt: Optional[Decimal] = None
    can_pay_with_credit: Optional[bool] = None
    address_link: Optional[str] = None
    requires_billing: Optional[bool] = None
    credit_override_enabled: Optional[bool] = None


def initialize_branch_credit_from_corporate(client: Client) -> bool:
    """
    Copy corporate credit policy to a new branch while keeping branch ledger state.

    Returns True when any credit policy/configuration data was copied.
    """
    if client.type != 'branch' or client.corporate_id is None:
        return False

    from clients.models import ClientCreditConfig

    corporate = client.corporate
    changed_fields = []

    if client.credit_limit != corporate.credit_limit:
        client.credit_limit = corporate.credit_limit
        changed_fields.append('credit_limit')

    if client.can_pay_with_credit != corporate.can_pay_with_credit:
        client.can_pay_with_credit = corporate.can_pay_with_credit
        changed_fields.append('can_pay_with_credit')

    try:
        corporate_config = corporate.credit_config
    except ClientCreditConfig.DoesNotExist:
        corporate_config = None

    if (
        corporate_config
        and corporate_config.payment_term_type == 'invoice_due'
        and not client.requires_billing
    ):
        client.requires_billing = True
        changed_fields.append('requires_billing')

    if changed_fields:
        client.save(update_fields=[*changed_fields, 'updated_at'])

    if not corporate_config:
        return bool(changed_fields)

    ClientCreditConfig.objects.update_or_create(
        client=client,
        defaults={
            'payment_term_type': corporate_config.payment_term_type,
            'cutoff_day': corporate_config.cutoff_day,
            'max_payment_days': corporate_config.max_payment_days,
            'first_notification_days': corporate_config.first_notification_days,
            'second_notification_days': corporate_config.second_notification_days,
            'overdue_notification_days': corporate_config.overdue_notification_days,
        },
    )
    return True


def _has_credit_policy_update(update_data: ClientUpdateData) -> bool:
    return (
        update_data.credit_limit is not None
        or update_data.can_pay_with_credit is not None
    )


def _branch_credit_policy_edit_allowed(client: Client, update_data: ClientUpdateData) -> bool:
    client_type = update_data.type if update_data.type is not None else client.type
    credit_override_enabled = (
        update_data.credit_override_enabled
        if update_data.credit_override_enabled is not None
        else client.credit_override_enabled
    )
    return client_type != 'branch' or credit_override_enabled


def update_client(client: Client, update_data: ClientUpdateData, user: User) -> Client:
    """
    Update a client with the provided data.
    
    Args:
        client: Client instance to update
        update_data: ClientUpdateData instance with fields to update
        user: User performing the update (for audit trail)
    
    Returns:
        Updated Client instance
    
    Raises:
        ValueError: If validation fails
    """
    if _has_credit_policy_update(update_data) and not _branch_credit_policy_edit_allowed(client, update_data):
        raise ValueError(
            'La configuración de crédito se administra desde el corporativo para esta sucursal.'
        )

    # Track if any changes were made
    updated = False
    
    # Update only the fields that are not None in update_data
    if update_data.name is not None:
        client.name = update_data.name
        updated = True
    
    if update_data.active is not None:
        client.active = update_data.active
        updated = True
    
    if update_data.note is not None:
        client.note = update_data.note
        updated = True
    
    if update_data.type is not None:
        client.type = update_data.type
        updated = True
    
    if update_data.corporate_id is not None:
        if update_data.corporate_id:
            try:
                corporate = Client.objects.get(pk=update_data.corporate_id, type='corporate')
                client.corporate = corporate
            except Client.DoesNotExist:
                raise ValueError(f"Corporate client with ID {update_data.corporate_id} not found")
        else:
            client.corporate = None
        updated = True
    
    if update_data.credit_limit is not None:
        client.credit_limit = update_data.credit_limit
        updated = True
    
    if update_data.can_pay_with_credit is not None:
        client.can_pay_with_credit = update_data.can_pay_with_credit
        updated = True
    
    if update_data.address_link is not None:
        client.address_link = update_data.address_link
        updated = True
    
    # Handle recurring billing changes before saving the client so any existing
    # active schedule is disabled when recurring billing is turned off.
    if update_data.requires_billing is not None:
        # If disabling recurring billing, keep fiscal data but disable schedule.
        if update_data.requires_billing is False and client.requires_billing is True:
            invoice_service.disable_billing_for_client(client.id)
        
        client.requires_billing = update_data.requires_billing
        updated = True

    if update_data.credit_override_enabled is not None:
        client.credit_override_enabled = update_data.credit_override_enabled
        updated = True
    
    # Note: balance and current_debt should be updated through transaction services
    # not directly, so we skip them here for safety
    
    if updated:
        # Run model validation
        client.full_clean()
        # Save the changes
        client.save()
    
    return client
