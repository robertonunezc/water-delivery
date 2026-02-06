from datetime import date
from billing import services as billing_service

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
    requires_note_for_credit: Optional[bool] = None
    address_link: Optional[str] = None
    requires_billing: Optional[bool] = None


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
    
    if update_data.requires_note_for_credit is not None:
        client.requires_note_for_credit = update_data.requires_note_for_credit
        updated = True
    
    if update_data.address_link is not None:
        client.address_link = update_data.address_link
        updated = True
    
    # Handle requires_billing changes - must be done BEFORE saving the client
    # because we need to delete billing data/frequency while client still has requires_billing=True
    if update_data.requires_billing is not None:
        # If disabling billing, remove billing data and frequency first
        if update_data.requires_billing is False and client.requires_billing is True:
            billing_service.disable_billing_for_client(client.id)
        
        client.requires_billing = update_data.requires_billing
        updated = True
    
    # Note: balance and current_debt should be updated through transaction services
    # not directly, so we skip them here for safety
    
    if updated:
        # Run model validation
        client.full_clean()
        # Save the changes
        client.save()
    
    return client