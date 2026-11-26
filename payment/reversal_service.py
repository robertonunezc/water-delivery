"""Append-only payment and standalone balance deposit reversal service."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import transaction
from django.utils import timezone

from clients.models import BalanceTransaction, Client, CreditTransaction
from orders.models import Order, OrderSplit
from orders.services.credit_lock_service import lock_order_credit_clients
from payment.models import (
    PAYMENT_ENTRY_KIND_PAYMENT,
    PAYMENT_ENTRY_KIND_REVERSAL,
    Payment,
    PaymentCollection,
)

logger = logging.getLogger(__name__)

ZERO = Decimal('0.00')
PREVIEW_TOKEN_MAX_AGE_SECONDS = 900
_SIGNER_SALT = 'payment.reversal.preview.v1'


class ReversalError(ValueError):
    """Base error for payment/deposit reversal failures."""


class ReversalTokenError(ReversalError):
    """Raised when a reversal preview token is missing, invalid, or expired."""


class ReversalBlockedError(ReversalError):
    """Raised when a planned reversal cannot proceed due to blocking rules."""

    def __init__(self, plan: PaymentReversalPlan | BalanceDepositReversalPlan) -> None:
        self.plan = plan
        super().__init__(' '.join(plan.blocking_reasons) or 'No se puede revertir el movimiento.')


class StaleReversalPreviewError(ReversalError):
    """Raised when DB state changed between preview and confirmation."""

    def __init__(self, plan: PaymentReversalPlan | BalanceDepositReversalPlan) -> None:
        self.plan = plan
        super().__init__(
            'El estado financiero cambió desde la vista previa. '
            'Revisa los efectos actualizados antes de confirmar.'
        )


@dataclass(frozen=True)
class BalanceAccountEffect:
    client_id: int
    client_name: str
    balance_before: Decimal
    restored_amount: Decimal
    removed_amount: Decimal
    balance_after: Decimal
    shortage: Decimal


@dataclass(frozen=True)
class CreditAccountEffect:
    client_id: int
    client_name: str
    debt_before: Decimal
    debt_delta: Decimal
    debt_after: Decimal
    credit_limit: Decimal
    available_credit_after: Decimal
    source_transaction_id: Optional[int]


@dataclass(frozen=True)
class InvoiceImpact:
    invoice_id: int
    folio: str
    status_display: str
    paid_before: Decimal
    paid_after: Decimal
    state_before: str
    state_after: str


@dataclass(frozen=True)
class PaymentReversalPlan:
    payment_id: int
    order_id: int
    payer_id: int
    payer_name: str
    order_client_id: int
    order_client_name: str
    method: str
    method_display: str
    amount: Decimal
    original_date: object
    can_reverse: bool
    blocking_reasons: list[str]
    balance_effects: list[BalanceAccountEffect]
    credit_effects: list[CreditAccountEffect]
    order_total: Decimal
    order_paid_before: Decimal
    order_paid_after: Decimal
    order_unpaid_before: Decimal
    order_unpaid_after: Decimal
    order_credit_before: Decimal
    order_credit_after: Decimal
    excess_amount: Decimal
    excess_already_removed: bool
    excess_transaction_id: Optional[int]
    balance_deduction_tx_ids: list[int]
    credit_payment_tx_ids: list[int]
    invoice_impacts: list[InvoiceImpact]
    fingerprint: str


@dataclass(frozen=True)
class BalanceDepositReversalPlan:
    transaction_id: int
    client_id: int
    client_name: str
    amount: Decimal
    original_date: object
    notes: str
    can_reverse: bool
    blocking_reasons: list[str]
    balance_before: Decimal
    balance_after: Decimal
    shortage: Decimal
    fingerprint: str


def is_payment_manager(user: AbstractBaseUser | None) -> bool:
    """Return True if user is an active Django staff/admin or manager employee."""
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True
    employee = getattr(user, 'employee', None)
    return bool(employee and employee.deleted_at is None and employee.position == 'manager')


def require_payment_manager(user: AbstractBaseUser | None) -> None:
    """Raise PermissionDenied unless user has manager/admin payment authority."""
    if not is_payment_manager(user):
        raise PermissionDenied('Solo gerentes o administradores pueden gestionar o revertir pagos.')


def sign_reversal_token(kind: str, target_id: int, fingerprint: str) -> str:
    """Return an expiring signed token binding the preview to a target and state fingerprint."""
    payload = json.dumps({'k': kind, 'id': target_id, 'fp': fingerprint}, sort_keys=True)
    return TimestampSigner(salt=_SIGNER_SALT).sign(payload)


def verify_reversal_token(
    token: str | None,
    kind: str,
    target_id: int,
    max_age: int = PREVIEW_TOKEN_MAX_AGE_SECONDS,
) -> str:
    """Verify preview token and return its expected state fingerprint."""
    if not token:
        raise ReversalTokenError('Falta el token de confirmación de vista previa.')
    try:
        raw = TimestampSigner(salt=_SIGNER_SALT).unsign(token, max_age=max_age)
        data = json.loads(raw)
    except SignatureExpired as exc:
        raise ReversalTokenError('La vista previa expiró. Recarga para confirmar nuevamente.') from exc
    except (BadSignature, ValueError, TypeError) as exc:
        raise ReversalTokenError('Token de vista previa inválido.') from exc

    if data.get('k') != kind or data.get('id') != target_id or not data.get('fp'):
        raise ReversalTokenError('El token de vista previa no corresponde a este movimiento.')
    return str(data['fp'])


def _compute_fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _order_outstanding_credit(order: Order) -> Decimal:
    summary = CreditTransaction.objects.filter(reference_order=order).aggregate_summary()
    return max(summary['total_purchases'] - summary['total_payments'], ZERO)


def _check_payment_eligibility(payment: Payment) -> list[str]:
    reasons: list[str] = []
    if payment.entry_kind != PAYMENT_ENTRY_KIND_PAYMENT:
        reasons.append('Este movimiento ya es una reversión y no puede revertirse nuevamente.')
    if payment.method == 'pending_credit':
        reasons.append('Los registros de crédito pendiente no son pagos recibidos reversibles.')
    if payment.status != 'completed':
        reasons.append(f'Solo se pueden revertir pagos completados (estado actual: {payment.status_display()}).')
    if payment.has_reversal:
        reasons.append('Este pago ya cuenta con una reversión registrada.')
    return reasons


def _check_historical_attribution(
    payment: Payment,
    balance_txs: list[BalanceTransaction],
) -> list[str]:
    reasons: list[str] = []
    if payment.method == 'balance' and not balance_txs:
        reasons.append(
            'Requiere revisión: no se encontró el movimiento de saldo vinculado a este pago con saldo.'
        )
    if payment.collection_id is None:
        unlinked_excess = BalanceTransaction.objects.filter(
            reference_order=payment.order,
            transaction_type='added_in_order',
            reversal_transaction__isnull=True,
        ).exists()
        if unlinked_excess:
            reasons.append(
                'Requiere revisión: existen excedentes históricos en esta orden sin vínculo de cobro explícito.'
            )
    return reasons


def _check_legacy_split_credit_attribution(
    payment: Payment,
    credit_txs: list[CreditTransaction],
) -> list[str]:
    if credit_txs:
        return []
    order = payment.order
    if CreditTransaction.objects.filter(reference_order=order).exists():
        return []
    if order.payments.filter(method='pending_credit').exists():
        return []
    parent_splits = OrderSplit.objects.filter(child_order=order).select_related('source_order')
    for split in parent_splits:
        source = split.source_order
        source_has_credit = (
            source.payments.filter(method='pending_credit', status='pending').exists()
            or _order_outstanding_credit(source) > ZERO
        )
        if source_has_credit:
            return [
                f'Requiere revisión: este pedido es una división histórica del pedido #{source.pk}, '
                f'que aún conserva crédito pendiente sin redistribuir. '
                f'Concilia el crédito de la división antes de revertir este pago.'
            ]
    return []


def _plan_balance_effects(
    balance_txs: list[BalanceTransaction],
    excess_tx: BalanceTransaction | None,
) -> tuple[list[BalanceAccountEffect], list[str]]:
    restored_by_client: dict[int, Decimal] = {}
    removed_by_client: dict[int, Decimal] = {}
    clients_by_id: dict[int, Client] = {}

    for tx in balance_txs:
        clients_by_id[tx.client_id] = tx.client
        restored_by_client[tx.client_id] = restored_by_client.get(tx.client_id, ZERO) + Decimal(str(tx.amount))

    if excess_tx is not None:
        clients_by_id[excess_tx.client_id] = excess_tx.client
        removed_by_client[excess_tx.client_id] = (
            removed_by_client.get(excess_tx.client_id, ZERO) + Decimal(str(excess_tx.amount))
        )

    effects: list[BalanceAccountEffect] = []
    reasons: list[str] = []
    for client_id in sorted(clients_by_id):
        client = clients_by_id[client_id]
        before = Decimal(str(client.balance))
        restored = restored_by_client.get(client_id, ZERO)
        removed = removed_by_client.get(client_id, ZERO)
        after = before + restored - removed
        shortage = max(-after, ZERO)
        effects.append(
            BalanceAccountEffect(
                client_id=client.pk,
                client_name=client.name,
                balance_before=before,
                restored_amount=restored,
                removed_amount=removed,
                balance_after=after,
                shortage=shortage,
            )
        )
        if shortage > ZERO:
            reasons.append(
                f'Saldo insuficiente en {client.name}: faltan ${shortage:.2f} para retirar el excedente. '
                f'Cancela primero los pagos con saldo más recientes.'
            )
    return effects, reasons


def _plan_credit_effects(
    payment: Payment,
    credit_txs: list[CreditTransaction],
) -> list[CreditAccountEffect]:
    effects: list[CreditAccountEffect] = []
    if credit_txs:
        deltas_by_client: dict[int, Decimal] = {}
        for tx in credit_txs:
            account = tx.client
            prev_delta = deltas_by_client.get(account.pk, ZERO)
            before = Decimal(str(account.current_debt)) + prev_delta
            delta = Decimal(str(tx.amount))
            after = before + delta
            deltas_by_client[account.pk] = prev_delta + delta
            effects.append(
                CreditAccountEffect(
                    client_id=account.pk,
                    client_name=account.name,
                    debt_before=before,
                    debt_delta=delta,
                    debt_after=after,
                    credit_limit=Decimal(str(account.credit_limit)),
                    available_credit_after=max(Decimal(str(account.credit_limit)) - after, ZERO),
                    source_transaction_id=tx.pk,
                )
            )
        return effects

    # Original non-credit payment made at order creation: unpaid amount becomes credit debt.
    account = payment.order.get_credit_account()
    before = Decimal(str(account.current_debt))
    delta = Decimal(str(payment.amount))
    after = before + delta
    effects.append(
        CreditAccountEffect(
            client_id=account.pk,
            client_name=account.name,
            debt_before=before,
            debt_delta=delta,
            debt_after=after,
            credit_limit=Decimal(str(account.credit_limit)),
            available_credit_after=max(Decimal(str(account.credit_limit)) - after, ZERO),
            source_transaction_id=None,
        )
    )
    return effects


def _invoice_state_label(paid: Decimal, total: Decimal) -> str:
    if paid >= total and total > ZERO:
        return 'Pagada'
    if paid > ZERO:
        return 'Pago parcial'
    return 'Pendiente'


def _plan_invoice_impacts(order: Order, payment_amount: Decimal) -> list[InvoiceImpact]:
    from invoice.models import InvoiceOrderLink

    impacts: list[InvoiceImpact] = []
    links = InvoiceOrderLink.objects.filter(order=order).select_related('invoice')
    for link in links:
        inv = link.invoice
        inv_total = Decimal(str(inv.amount))
        paid_before = Decimal(str(inv.total_payments))
        paid_after = max(paid_before - payment_amount, ZERO)
        impacts.append(
            InvoiceImpact(
                invoice_id=inv.pk,
                folio=inv.folio or f'#{inv.pk}',
                status_display=inv.get_status_display(),
                paid_before=paid_before,
                paid_after=paid_after,
                state_before=_invoice_state_label(paid_before, inv_total),
                state_after=_invoice_state_label(paid_after, inv_total),
            )
        )
    return impacts


def plan_payment_reversal(payment_id: int) -> PaymentReversalPlan:
    """Build a deterministic reversal plan for one order payment without writing to DB."""
    payment = (
        Payment.objects.select_related(
            'order',
            'order__client',
            'order__credit_account',
            'client',
            'collection',
            'collection__excess_balance_transaction',
            'collection__excess_balance_transaction__client',
            'collection__excess_reversal_transaction',
        )
        .get(pk=payment_id)
    )
    order = payment.order
    reasons = _check_payment_eligibility(payment)

    balance_txs = list(
        BalanceTransaction.objects.filter(
            reference_payment=payment,
            transaction_type='payment',
            reversal_transaction__isnull=True,
        ).select_related('client').order_by('pk')
    )
    credit_txs = list(
        CreditTransaction.objects.filter(
            reference_payment=payment,
            transaction_type__in=['payment', 'payment_from_balance'],
            reversal_transaction__isnull=True,
        ).select_related('client').order_by('pk')
    )
    reasons.extend(_check_historical_attribution(payment, balance_txs))
    reasons.extend(_check_legacy_split_credit_attribution(payment, credit_txs))

    excess_tx = None
    excess_already_removed = False
    excess_amount = ZERO
    if payment.collection and payment.collection.excess_balance_transaction_id:
        if payment.collection.excess_reversal_transaction_id:
            excess_already_removed = True
        else:
            excess_tx = payment.collection.excess_balance_transaction
            excess_amount = Decimal(str(excess_tx.amount))

    balance_effects, balance_reasons = _plan_balance_effects(balance_txs, excess_tx)
    reasons.extend(balance_reasons)
    credit_effects = _plan_credit_effects(payment, credit_txs)

    order_total = Decimal(str(order.total_amount))
    order_paid_before = Decimal(str(order.total_paid))
    order_paid_after = max(order_paid_before - Decimal(str(payment.amount)), ZERO)
    order_unpaid_before = max(order_total - order_paid_before, ZERO)
    order_unpaid_after = max(order_total - order_paid_after, ZERO)
    order_credit_before = _order_outstanding_credit(order)
    order_credit_after = order_credit_before + sum((e.debt_delta for e in credit_effects), ZERO)
    invoice_impacts = _plan_invoice_impacts(order, Decimal(str(payment.amount)))

    fingerprint = _compute_fingerprint({
        'payment_id': payment.pk,
        'status': payment.status,
        'has_reversal': payment.has_reversal,
        'amount': str(payment.amount),
        'balance_tx_ids': [tx.pk for tx in balance_txs],
        'credit_tx_ids': [tx.pk for tx in credit_txs],
        'excess_tx_id': excess_tx.pk if excess_tx else None,
        'excess_already_removed': excess_already_removed,
        'balances': [(e.client_id, str(e.balance_before), str(e.balance_after)) for e in balance_effects],
        'credits': [(e.client_id, str(e.debt_before), str(e.debt_after)) for e in credit_effects],
        'order_paid_before': str(order_paid_before),
        'can_reverse': len(reasons) == 0,
    })

    return PaymentReversalPlan(
        payment_id=payment.pk,
        order_id=order.pk,
        payer_id=payment.client_id,
        payer_name=payment.client.name,
        order_client_id=order.client_id,
        order_client_name=order.client.name,
        method=payment.method,
        method_display=payment.get_method_display(),
        amount=Decimal(str(payment.amount)),
        original_date=payment.date,
        can_reverse=len(reasons) == 0,
        blocking_reasons=reasons,
        balance_effects=balance_effects,
        credit_effects=credit_effects,
        order_total=order_total,
        order_paid_before=order_paid_before,
        order_paid_after=order_paid_after,
        order_unpaid_before=order_unpaid_before,
        order_unpaid_after=order_unpaid_after,
        order_credit_before=order_credit_before,
        order_credit_after=order_credit_after,
        excess_amount=excess_amount,
        excess_already_removed=excess_already_removed,
        excess_transaction_id=excess_tx.pk if excess_tx else None,
        balance_deduction_tx_ids=[tx.pk for tx in balance_txs],
        credit_payment_tx_ids=[tx.pk for tx in credit_txs],
        invoice_impacts=invoice_impacts,
        fingerprint=fingerprint,
    )


def sync_invoice_order_links_for_order(order: Order) -> None:
    """Synchronize stored InvoiceOrderLink payment flags with order net paid amount."""
    from invoice.models import InvoiceOrderLink

    fresh_order = Order.objects.prefetch_related('payments').get(pk=order.pk)
    paid = Decimal(str(fresh_order.total_paid))
    total = Decimal(str(fresh_order.total_amount))
    is_paid = paid >= total and total > ZERO
    partially_paid = ZERO < paid < total
    InvoiceOrderLink.objects.filter(order=fresh_order).update(
        is_paid=is_paid,
        partially_paid=partially_paid,
    )


def _apply_balance_mutation(
    client: Client,
    delta: Decimal,
    transaction_type: str,
    user: AbstractBaseUser | None,
    reason: str,
    reference_order: Order | None,
    reference_payment: Payment | None,
    reverses_transaction: BalanceTransaction | None,
    notes: str,
) -> BalanceTransaction:
    before = Decimal(str(client.balance))
    after = before + delta
    if after < ZERO:
        raise ReversalError(f'Saldo insuficiente en {client.name}.')
    client.balance = after
    client.save(update_fields=['balance', 'updated_at'])
    return BalanceTransaction.objects.create(
        client=client,
        transaction_type=transaction_type,
        amount=abs(delta),
        balance_before=before,
        balance_after=after,
        notes=notes,
        reversal_reason=reason,
        reference_order=reference_order,
        reference_payment=reference_payment,
        reverses_transaction=reverses_transaction,
        created_by=user,
        date=timezone.now(),
    )


def _apply_credit_debt_increase(
    account: Client,
    amount: Decimal,
    order: Order,
    reversal_payment: Payment,
    user: AbstractBaseUser | None,
    reason: str,
    reverses_transaction: CreditTransaction | None,
) -> CreditTransaction:
    before = Decimal(str(account.current_debt))
    after = before + amount
    account.current_debt = after
    account.save(update_fields=['current_debt', 'updated_at'])
    if order.credit_account_id is None:
        order.credit_account = account
        order.capture_credit_terms(account)
        order.save(update_fields=['credit_account', 'credit_terms_snapshot', 'updated_at'])
    return CreditTransaction.objects.create(
        client=account,
        transaction_type='payment_reversal',
        amount=amount,
        debt_before=before,
        debt_after=after,
        credit_limit_before=account.credit_limit,
        credit_limit_after=account.credit_limit,
        notes=f'Reversión de pago #{reversal_payment.reversal_of_id} (orden #{order.pk}): {reason}',
        date=timezone.localdate(),
        reference_order=order,
        reference_payment=reversal_payment,
        reverses_transaction=reverses_transaction,
        created_by=user,
    )


def _lock_payment_reversal_records(payment_id: int) -> tuple[Payment, dict[int, Client]]:
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    if payment.collection_id:
        PaymentCollection.objects.select_for_update().get(pk=payment.collection_id)
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    lock_order_credit_clients([order.pk])

    client_ids = {payment.client_id, order.client_id, order.get_credit_account().pk}
    for tx in BalanceTransaction.objects.select_for_update().filter(reference_payment=payment):
        client_ids.add(tx.client_id)
    for tx in CreditTransaction.objects.select_for_update().filter(reference_payment=payment):
        client_ids.add(tx.client_id)
    if payment.collection_id and payment.collection.excess_balance_transaction_id:
        excess = BalanceTransaction.objects.select_for_update().get(
            pk=payment.collection.excess_balance_transaction_id
        )
        client_ids.add(excess.client_id)

    locked_clients = {
        c.pk: c for c in Client.objects.select_for_update().filter(pk__in=sorted(client_ids)).order_by('pk')
    }
    return payment, locked_clients


@transaction.atomic
def execute_payment_reversal(
    payment_id: int,
    user: AbstractBaseUser | None,
    reason: str,
    *,
    preview_token: str | None = None,
    require_token: bool = True,
) -> Payment:
    """Atomically execute a single whole-payment append-only reversal."""
    require_payment_manager(user)
    clean_reason = (reason or '').strip()
    if not clean_reason:
        raise ReversalError('Debes indicar un motivo para revertir el pago.')

    expected_fp = (
        verify_reversal_token(preview_token, 'payment', payment_id)
        if require_token
        else None
    )

    original, locked_clients = _lock_payment_reversal_records(payment_id)
    plan = plan_payment_reversal(payment_id)
    if expected_fp is not None and plan.fingerprint != expected_fp:
        raise StaleReversalPreviewError(plan)
    if not plan.can_reverse:
        raise ReversalBlockedError(plan)

    reversal_payment = Payment(
        amount=original.amount,
        method=original.method,
        client=original.client,
        order=original.order,
        status='completed',
        entry_kind=PAYMENT_ENTRY_KIND_REVERSAL,
        reversal_of=original,
        collection=original.collection,
        reversal_reason=clean_reason,
        created_by=user,
    )
    reversal_payment.save(apply_accounting=False)

    for tx_id in plan.balance_deduction_tx_ids:
        orig_tx = BalanceTransaction.objects.get(pk=tx_id)
        _apply_balance_mutation(
            client=locked_clients[orig_tx.client_id],
            delta=Decimal(str(orig_tx.amount)),
            transaction_type='payment_reversal',
            user=user,
            reason=clean_reason,
            reference_order=original.order,
            reference_payment=reversal_payment,
            reverses_transaction=orig_tx,
            notes=f'Restitución de saldo por reversión de pago #{original.pk}: {clean_reason}',
        )

    if plan.excess_transaction_id is not None and original.collection_id:
        excess_tx = BalanceTransaction.objects.get(pk=plan.excess_transaction_id)
        comp_excess = _apply_balance_mutation(
            client=locked_clients[excess_tx.client_id],
            delta=-Decimal(str(excess_tx.amount)),
            transaction_type='added_in_order_reversal',
            user=user,
            reason=clean_reason,
            reference_order=excess_tx.reference_order,
            reference_payment=reversal_payment,
            reverses_transaction=excess_tx,
            notes=f'Retiro de excedente por reversión de pago #{original.pk}: {clean_reason}',
        )
        collection = PaymentCollection.objects.get(pk=original.collection_id)
        collection.excess_reversal_transaction = comp_excess
        collection.save(update_fields=['excess_reversal_transaction', 'updated_at'])

    for effect in plan.credit_effects:
        source_tx = (
            CreditTransaction.objects.get(pk=effect.source_transaction_id)
            if effect.source_transaction_id
            else None
        )
        _apply_credit_debt_increase(
            account=locked_clients[effect.client_id],
            amount=effect.debt_delta,
            order=original.order,
            reversal_payment=reversal_payment,
            user=user,
            reason=clean_reason,
            reverses_transaction=source_tx,
        )

    sync_invoice_order_links_for_order(original.order)
    logger.info(
        'Reversed payment #%s with reversal #%s by user %s',
        original.pk,
        reversal_payment.pk,
        getattr(user, 'pk', None),
    )
    return reversal_payment


def plan_balance_deposit_reversal(transaction_id: int) -> BalanceDepositReversalPlan:
    """Build a deterministic reversal plan for one standalone balance deposit."""
    tx = BalanceTransaction.objects.select_related('client').get(pk=transaction_id)
    reasons: list[str] = []
    if tx.transaction_type != 'deposit':
        reasons.append('Solo se pueden revertir abonos a saldo (depósitos).')
    if tx.reference_order_id is not None or tx.reference_payment_id is not None:
        reasons.append('Este movimiento está vinculado a un pedido o pago; revierte el pago correspondiente.')
    if BalanceTransaction.objects.filter(reverses_transaction=tx).exists():
        reasons.append('Este abono a saldo ya fue revertido.')

    amount = Decimal(str(tx.amount))
    before = Decimal(str(tx.client.balance))
    after = before - amount
    shortage = max(-after, ZERO)
    if shortage > ZERO:
        reasons.append(
            f'Saldo insuficiente en {tx.client.name}: faltan ${shortage:.2f}. '
            f'El saldo ya fue utilizado; cancela primero los pagos con saldo más recientes.'
        )

    fingerprint = _compute_fingerprint({
        'transaction_id': tx.pk,
        'client_id': tx.client_id,
        'amount': str(amount),
        'balance_before': str(before),
        'can_reverse': len(reasons) == 0,
    })
    return BalanceDepositReversalPlan(
        transaction_id=tx.pk,
        client_id=tx.client_id,
        client_name=tx.client.name,
        amount=amount,
        original_date=tx.date or tx.created_at,
        notes=tx.notes or '',
        can_reverse=len(reasons) == 0,
        blocking_reasons=reasons,
        balance_before=before,
        balance_after=after,
        shortage=shortage,
        fingerprint=fingerprint,
    )


@transaction.atomic
def execute_balance_deposit_reversal(
    transaction_id: int,
    user: AbstractBaseUser | None,
    reason: str,
    *,
    preview_token: str | None = None,
    require_token: bool = True,
) -> BalanceTransaction:
    """Atomically reverse one standalone balance deposit via an append-only entry."""
    require_payment_manager(user)
    clean_reason = (reason or '').strip()
    if not clean_reason:
        raise ReversalError('Debes indicar un motivo para revertir el abono a saldo.')

    expected_fp = (
        verify_reversal_token(preview_token, 'deposit', transaction_id)
        if require_token
        else None
    )

    orig_tx = BalanceTransaction.objects.select_for_update().get(pk=transaction_id)
    locked_client = Client.objects.select_for_update().get(pk=orig_tx.client_id)
    plan = plan_balance_deposit_reversal(transaction_id)
    if expected_fp is not None and plan.fingerprint != expected_fp:
        raise StaleReversalPreviewError(plan)
    if not plan.can_reverse:
        raise ReversalBlockedError(plan)

    reversal_tx = _apply_balance_mutation(
        client=locked_client,
        delta=-Decimal(str(orig_tx.amount)),
        transaction_type='deposit_reversal',
        user=user,
        reason=clean_reason,
        reference_order=None,
        reference_payment=None,
        reverses_transaction=orig_tx,
        notes=f'Reversión de abono a saldo #{orig_tx.pk}: {clean_reason}',
    )
    logger.info(
        'Reversed balance deposit #%s with tx #%s by user %s',
        orig_tx.pk,
        reversal_tx.pk,
        getattr(user, 'pk', None),
    )
    return reversal_tx
