from __future__ import annotations

from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest

from clients.models import Client, CreditTransaction

ZERO = Decimal("0.00")
DEBT_INCREASE_TYPES = ("purchase", "interest", "fee", "payment_reversal")
DEBT_DECREASE_TYPES = (
    "payment",
    "payment_from_balance",
    "forgiveness",
    "purchase_reversal",
)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or ZERO))


def _get_inherited_branch_debt(client: Client, credit_account: Client) -> Decimal:
    summary = (
        credit_account.credit_transactions.filter(reference_order__client=client)
        .aggregate_summary()
    )
    if summary["transaction_count"] == 0:
        return _decimal(client.current_debt)
    debt = summary["total_purchases"] - summary["total_payments"]
    return max(debt, ZERO)


def get_client_display_current_debt(client: Client) -> Decimal:
    """Return the client debt amount that user-facing screens should display."""
    credit_account = client.get_credit_account()
    if credit_account.pk == client.pk:
        return _decimal(client.current_debt)
    return _get_inherited_branch_debt(client, credit_account)


def with_display_current_debt(queryset: QuerySet[Client]) -> QuerySet[Client]:
    """Annotate clients with debt including inherited branch credit ledgers."""
    amount_field = DecimalField(max_digits=12, decimal_places=2)
    zero_value = Value(ZERO, output_field=amount_field)
    inherited_debt = (
        CreditTransaction.objects.filter(
            client_id=OuterRef("corporate_id"),
            reference_order__client_id=OuterRef("pk"),
        )
        .values("reference_order__client_id")
        .annotate(
            total_purchases=Coalesce(
                Sum("amount", filter=Q(transaction_type__in=DEBT_INCREASE_TYPES)),
                zero_value,
            ),
            total_payments=Coalesce(
                Sum("amount", filter=Q(transaction_type__in=DEBT_DECREASE_TYPES)),
                zero_value,
            ),
        )
        .annotate(
            net_debt=Greatest(
                ExpressionWrapper(
                    F("total_purchases") - F("total_payments"),
                    output_field=amount_field,
                ),
                zero_value,
            )
        )
        .values("net_debt")[:1]
    )

    return queryset.annotate(
        display_current_debt=Case(
            When(
                type="branch",
                corporate_id__isnull=False,
                credit_override_enabled=False,
                then=Coalesce(
                    Subquery(inherited_debt, output_field=amount_field),
                    F("current_debt"),
                    zero_value,
                ),
            ),
            default=F("current_debt"),
            output_field=amount_field,
        )
    )
