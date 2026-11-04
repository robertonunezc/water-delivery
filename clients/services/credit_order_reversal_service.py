from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from clients.models import Client, CreditTransaction
from orders.models import Order

ZERO = Decimal('0.00')


def _record_reversal(
    account: Client, order: Order, amount: Decimal, transaction_type: str,
    user: AbstractBaseUser | None, payment_id: int | None = None,
) -> None:
    before = account.current_debt
    account.current_debt += amount if transaction_type == 'payment_reversal' else -amount
    account.save(update_fields=['current_debt', 'updated_at'])
    CreditTransaction.objects.create(
        client=account, reference_order=order, reference_payment_id=payment_id,
        transaction_type=transaction_type, amount=amount,
        debt_before=before, debt_after=account.current_debt,
        credit_limit_before=account.credit_limit, credit_limit_after=account.credit_limit,
        created_by=user, date=timezone.localdate(),
        notes=f'Reversión por cancelación del pedido transferido #{order.pk}',
    )


@transaction.atomic
def reverse_transferred_order_credit(order: Order, user: AbstractBaseUser | None) -> None:
    """Reverse payments and net credit exposure on every historical debt account."""
    entries = CreditTransaction.objects.filter(reference_order=order)
    account_ids = entries.values_list('client_id', flat=True).distinct()
    accounts = Client.objects.select_for_update().filter(pk__in=account_ids).order_by('pk')
    for account in accounts:
        account_entries = entries.filter(client=account)
        summary = account_entries.aggregate_summary()
        remaining = summary['total_purchases'] - summary['total_payments']
        if remaining < ZERO or remaining > account.current_debt:
            raise ValueError('La deuda del pedido transferido requiere conciliación antes de cancelar.')
        payments = list(account_entries.filter(transaction_type__in=['payment', 'payment_from_balance']))
        exposure = remaining + sum((payment.amount for payment in payments), ZERO)
        for payment in payments:
            _record_reversal(account, order, payment.amount, 'payment_reversal', user, payment.reference_payment_id)
        if exposure:
            _record_reversal(account, order, exposure, 'purchase_reversal', user)
