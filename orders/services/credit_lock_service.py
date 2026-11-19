from django.db.models import Case, IntegerField, Q, Value, When

from clients.models import Client
from orders.models import Order


def lock_order_credit_clients(
    order_ids: list[int], *, extra_client_ids: list[int] | None = None,
) -> None:
    """Serialize credit switches before locking orders, payments or debt accounts."""
    client_ids = Order.objects.filter(pk__in=order_ids).values('client_id')
    branch_first = Case(
        When(type='branch', then=Value(0)), default=Value(1), output_field=IntegerField(),
    )
    list(
        Client.objects.select_for_update().filter(
            Q(pk__in=client_ids) | Q(pk__in=extra_client_ids or []),
        ).order_by(branch_first, 'pk')
    )


def lock_credit_policy_client(client_id: int) -> Client:
    """Lock branches before corporate policy edits that synchronize their settings."""
    branch_first = Case(
        When(type='branch', then=Value(0)), default=Value(1), output_field=IntegerField(),
    )
    accounts = list(
        Client.objects.select_for_update().filter(
            Q(pk=client_id) | Q(corporate_id=client_id, type='branch'),
        ).order_by(branch_first, 'pk')
    )
    return next(account for account in accounts if account.pk == client_id)
