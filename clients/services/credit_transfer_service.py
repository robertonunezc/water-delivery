from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from clients.models import Client, CreditDebtTransfer, CreditTransaction
from orders.models import Order

logger = logging.getLogger(__name__)
ZERO = Decimal('0.00')


@dataclass(frozen=True)
class CreditTransferItem:
    order: Order
    amount: Decimal


def _get_transfer_items(branch: Client, source: Client, lock: bool = False) -> list[CreditTransferItem]:
    orders = (
        Order.objects.active().with_payment_totals().for_credit_accounts([source.pk])
        .filter(client=branch).order_by('pk')
    )
    if lock:
        orders = orders.select_for_update(of=('self',))
    items = []
    for order in orders:
        summary = source.credit_transactions.filter(reference_order=order).aggregate_summary()
        amount = summary['total_purchases'] - summary['total_payments']
        if amount != order.total_amount - order.total_paid:
            raise ValueError(f'La deuda del pedido #{order.pk} requiere conciliación antes de transferir.')
        if amount == ZERO:
            continue
        items.append(CreditTransferItem(order=order, amount=amount))
    return items


def _validate_transfer_capacity(source: Client, target: Client, total: Decimal) -> None:
    required = target.current_debt + total
    if required > target.credit_limit:
        raise ValueError(f'El límite de destino debe ser al menos ${required:.2f} para transferir la deuda.')
    if total > source.current_debt:
        raise ValueError('La deuda de origen requiere conciliación antes de transferir.')


def preview_branch_credit_transfer(branch: Client, source: Client, target: Client) -> Decimal:
    """Read the transferable amount and reject unreconciled or over-limit debt."""
    total = sum((item.amount for item in _get_transfer_items(branch, source)), ZERO)
    _validate_transfer_capacity(source, target, total)
    return total


def validate_client_credit_switch(client: Client, enabled: bool, limit: Decimal | None = None) -> None:
    """Validate a form submission without changing financial state."""
    if not client.pk:
        return
    stored = Client.objects.select_related('corporate').get(pk=client.pk)
    if stored.type != 'branch':
        return
    if enabled == stored.credit_override_enabled:
        if enabled and limit is not None:
            stored.validate_credit_limit(limit)
        elif limit is not None and limit != stored.credit_limit:
            raise ValueError('La configuración de crédito se administra desde el corporativo para esta sucursal.')
        return
    source = stored.get_credit_account()
    target = stored if enabled else stored.corporate
    if enabled and limit is not None:
        target.credit_limit = limit
    preview_branch_credit_transfer(stored, source, target)


@transaction.atomic
def transfer_existing_branch_credit(branch: Client, user: AbstractBaseUser | None = None) -> Decimal:
    """Explicitly migrate old corporate-funded orders of an existing override branch."""
    branch = Client.objects.select_for_update().get(pk=branch.pk)
    if branch.type != 'branch' or not branch.credit_override_enabled or not branch.corporate_id:
        raise ValueError('La sucursal debe tener crédito propio y un corporativo asociado.')
    return transfer_branch_credit(branch, branch.corporate, branch, user)


def _record_entry(
    transfer: CreditDebtTransfer, account: Client, transaction_type: str, amount: Decimal,
) -> None:
    before = account.current_debt
    account.current_debt += amount if transaction_type == 'transfer_in' else -amount
    account.save(update_fields=['current_debt', 'updated_at'])
    CreditTransaction.objects.create(
        client=account, debt_transfer=transfer, transaction_type=transaction_type,
        amount=amount, debt_before=before, debt_after=account.current_debt,
        credit_limit_before=account.credit_limit, credit_limit_after=account.credit_limit,
        reference_order=transfer.order, created_by=transfer.created_by,
        date=timezone.localdate(),
        notes=f'Transferencia de deuda #{transfer.pk}: {transfer.source_account_id} → {transfer.target_account_id}',
    )


@transaction.atomic
def transfer_branch_credit(
    branch: Client, source: Client, target: Client, user: AbstractBaseUser | None,
) -> Decimal:
    """Move all unpaid branch credit together, preserving original sale history."""
    if source.pk == target.pk:
        return ZERO
    Client.objects.select_for_update().get(pk=branch.pk)
    accounts = {
        account.pk: account for account in Client.objects.select_for_update()
        .filter(pk__in=[source.pk, target.pk]).order_by('pk')
    }
    source_account, target_account = accounts[source.pk], accounts[target.pk]
    if target.pk == branch.pk:
        target_account.credit_limit = target.credit_limit
    items = _get_transfer_items(branch, source_account, lock=True)
    total = sum((item.amount for item in items), ZERO)
    _validate_transfer_capacity(source_account, target_account, total)
    for item in items:
        _transfer_order(item, source_account, target_account, user)
    if branch.pk in accounts:
        branch.current_debt = accounts[branch.pk].current_debt
    logger.info('Transferred branch credit debt', extra={'branch_id': branch.pk, 'amount': str(total)})
    return total


def _transfer_order(
    item: CreditTransferItem, source: Client, target: Client, user: AbstractBaseUser | None,
) -> None:
    item.order.capture_credit_terms(source)
    transfer = CreditDebtTransfer.objects.create(
        order=item.order, source_account=source, target_account=target,
        amount=item.amount, created_by=user,
    )
    _record_entry(transfer, source, 'transfer_out', item.amount)
    _record_entry(transfer, target, 'transfer_in', item.amount)
    item.order.credit_account = target
    item.order.save(update_fields=['credit_account', 'credit_terms_snapshot', 'updated_at'])
