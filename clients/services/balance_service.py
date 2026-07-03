"""
Balance and Credit Service

Handles all balance and credit mutations for clients.
All functions are wrapped with @transaction.atomic for consistency.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

from django.db import transaction

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from clients.models import Client, BalanceTransaction, CreditTransaction
    from orders.models import Order
    from payment.models import Payment

logger = logging.getLogger(__name__)


class PaymentResult(TypedDict, total=False):
    """Result type for payment operations."""

    success: bool
    error: str
    amount_paid: Decimal
    remaining_balance: Decimal
    remaining_debt: Decimal
    available_credit: Decimal


class TransferResult(TypedDict, total=False):
    """Result type for transfer operations."""

    success: bool
    error: str
    amount_transferred: Decimal
    source_balance: Decimal
    target_balance: Decimal


class FinancialSummary(TypedDict):
    """Type for financial summary data."""

    current_balance: Decimal
    current_debt: Decimal
    credit_limit: Decimal
    available_credit: Decimal
    balance_summary: dict
    credit_summary: dict
    period_start: object
    period_end: object


@transaction.atomic
def add_balance(
    client: "Client",
    amount: Decimal,
    transaction_type: str = "deposit",
    user: "User | None" = None,
    reference_order: "Order | None" = None,
    reference_payment: "Payment | None" = None,
    transfer_to_client: "Client | None" = None,
    notes: str | None = None,
) -> "BalanceTransaction":
    """
    Add money to client's balance with transaction history.

    Args:
        client: Client to add balance to
        amount: Amount to add (must be positive)
        transaction_type: Type of transaction (deposit, refund, transfer_in, adjustment, correction)
        user: User performing the transaction
        reference_order: Related order (if applicable)
        reference_payment: Related payment (if applicable)
        transfer_to_client: Source/target client for transfers (if applicable)
        notes: Additional notes

    Returns:
        BalanceTransaction: The created transaction record

    Raises:
        ValueError: If amount is not positive
    """
    from clients.models import BalanceTransaction

    if amount <= 0:
        raise ValueError("Amount must be positive")

    # Store previous balance
    balance_before = client.balance

    # Update balance
    client.balance += amount
    balance_after = client.balance

    # Save client
    client.save(update_fields=["balance", "updated_at"])

    # Create transaction record
    final_notes = notes or f"{transaction_type.replace('_', ' ').title()} de ${amount:.2f}"
    return BalanceTransaction.objects.create(
        client=client,
        transaction_type=transaction_type,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        notes=final_notes,
        reference_order=reference_order,
        reference_payment=reference_payment,
        transfer_to_client=transfer_to_client,
        created_by=user,
    )


@transaction.atomic
def deduct_balance(
    client: "Client",
    amount: Decimal,
    transaction_type: str = "payment",
    user: "User | None" = None,
    reference_order: "Order | None" = None,
    reference_payment: "Payment | None" = None,
    transfer_to_client: "Client | None" = None,
    notes: str | None = None,
) -> "BalanceTransaction | None":
    """
    Deduct money from client's balance with transaction history.

    Args:
        client: Client to deduct balance from
        amount: Amount to deduct (must be positive)
        transaction_type: Type of transaction (payment, transfer_out, adjustment, correction)
        user: User performing the transaction
        reference_order: Related order (if applicable)
        reference_payment: Related payment (if applicable)
        transfer_to_client: Target client for transfers (if applicable)
        notes: Additional notes

    Returns:
        BalanceTransaction if successful, None if insufficient balance

    Raises:
        ValueError: If amount is not positive
    """
    from clients.models import BalanceTransaction

    if amount <= 0:
        raise ValueError("Amount must be positive")

    if client.balance < amount:
        return None

    # Store previous balance
    balance_before = client.balance

    # Update balance
    client.balance -= amount
    balance_after = client.balance

    # Save client
    client.save(update_fields=["balance", "updated_at"])

    # Create transaction record
    final_notes = notes or f"{transaction_type.replace('_', ' ').title()} de ${amount:.2f}"
    return BalanceTransaction.objects.create(
        client=client,
        transaction_type=transaction_type,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        notes=final_notes,
        reference_order=reference_order,
        reference_payment=reference_payment,
        transfer_to_client=transfer_to_client,
        created_by=user,
    )


@transaction.atomic
def add_debt(
    client: "Client",
    amount: Decimal,
    transaction_type: str = "purchase",
    user: "User | None" = None,
    reference_order: "Order | None" = None,
    reference_payment: "Payment | None" = None,
    notes: str | None = None,
) -> "CreditTransaction | None":
    """
    Add to client's debt with transaction history.

    Args:
        client: Client to add debt to
        amount: Amount to add to debt (must be positive)
        transaction_type: Type of transaction (purchase, interest, fee, adjustment, correction)
        user: User performing the transaction
        reference_order: Related order (if applicable)
        reference_payment: Related payment (if applicable)
        notes: Additional notes

    Returns:
        CreditTransaction created for the debt increase.

    Raises:
        ValueError: If amount is invalid or the credit sale is not allowed.
    """
    from clients.models import Client, CreditTransaction
    from clients.services.pending_payment_service import client_has_overdue_credit

    if amount <= 0:
        raise ValueError("Amount must be positive")

    locked_client = Client.objects.select_for_update().get(pk=client.pk)
    if transaction_type == 'purchase' and not locked_client.can_use_credit_for_payment():
        raise ValueError('El cliente no tiene crédito disponible para esta venta.')
    if transaction_type == 'purchase' and client_has_overdue_credit(locked_client):
        raise ValueError(
            'El cliente tiene créditos vencidos y no puede realizar nuevas ventas a crédito.'
        )

    new_debt = locked_client.current_debt + amount
    if transaction_type == 'purchase' and new_debt > locked_client.credit_limit:
        raise ValueError(
            f'La venta excede el límite de crédito. Disponible: '
            f'${locked_client.get_available_credit():.2f}.'
        )

    # Store previous values
    debt_before = locked_client.current_debt
    credit_limit_before = locked_client.credit_limit

    # Update debt
    locked_client.current_debt = new_debt
    debt_after = locked_client.current_debt

    # Save client
    locked_client.save(update_fields=["current_debt", "updated_at"])
    client.current_debt = locked_client.current_debt

    # Create transaction record
    combined_notes = notes or f"{transaction_type.replace('_', ' ').title()} de ${amount:.2f}"
    return CreditTransaction.objects.create(
        client=client,
        transaction_type=transaction_type,
        amount=amount,
        debt_before=debt_before,
        debt_after=debt_after,
        credit_limit_before=credit_limit_before,
        credit_limit_after=locked_client.credit_limit,
        notes=combined_notes,
        reference_order=reference_order,
        reference_payment=reference_payment,
        created_by=user,
    )


@transaction.atomic
def pay_debt(
    client: "Client",
    amount: Decimal,
    transaction_type: str = "payment",
    user: "User | None" = None,
    reference_order: "Order | None" = None,
    reference_payment: "Payment | None" = None,
    notes: str | None = None,
) -> Decimal:
    """
    Pay down client's debt with transaction history.

    Args:
        client: Client to pay debt for
        amount: Amount to pay towards debt (must be positive)
        transaction_type: Type of transaction (payment, adjustment, forgiveness, correction)
        user: User performing the transaction
        reference_order: Related order (if applicable)
        reference_payment: Related payment (if applicable)
        notes: Additional notes

    Returns:
        Amount actually paid (limited by current debt)

    Raises:
        ValueError: If amount is not positive
    """
    from clients.models import Client, CreditTransaction

    if amount <= 0:
        raise ValueError("Amount must be positive")

    locked_client = Client.objects.select_for_update().get(pk=client.pk)
    payment_amount = min(amount, locked_client.current_debt)

    if payment_amount == 0:
        return Decimal("0")

    # Store previous values
    debt_before = locked_client.current_debt
    credit_limit_before = locked_client.credit_limit

    # Update debt
    locked_client.current_debt -= payment_amount
    debt_after = locked_client.current_debt

    # Save client
    locked_client.save(update_fields=["current_debt", "updated_at"])
    client.current_debt = locked_client.current_debt

    # Create transaction record
    final_notes = notes or f"{transaction_type.replace('_', ' ').title()} de ${payment_amount:.2f}"
    CreditTransaction.objects.create(
        client=client,
        transaction_type=transaction_type,
        amount=payment_amount,
        debt_before=debt_before,
        debt_after=debt_after,
        credit_limit_before=credit_limit_before,
        credit_limit_after=locked_client.credit_limit,
        notes=final_notes,
        reference_order=reference_order,
        reference_payment=reference_payment,
        created_by=user,
    )

    return payment_amount


@transaction.atomic
def reverse_balance_payment(
    payment: "Payment",
    user: "User | None" = None,
) -> "BalanceTransaction":
    """Restore client balance that was consumed by a balance payment."""
    amount = payment.balance_used or payment.amount
    return add_balance(
        client=payment.client,
        amount=amount,
        transaction_type="payment_reversal",
        user=user,
        reference_order=payment.order,
        reference_payment=payment,
        notes=f"Reversión de pago con saldo - Pedido #{payment.order_id}",
    )


@transaction.atomic
def reverse_added_order_balance(
    client: "Client",
    amount: Decimal,
    user: "User | None",
    reference_order: "Order",
) -> "BalanceTransaction | None":
    """Remove balance that was added to the client while processing an order."""
    return deduct_balance(
        client=client,
        amount=amount,
        transaction_type="added_in_order_reversal",
        user=user,
        reference_order=reference_order,
        notes=f"Reversión de saldo agregado en venta - Pedido #{reference_order.id}",
    )


@transaction.atomic
def reverse_credit_purchase(
    client: "Client",
    amount: Decimal,
    user: "User | None" = None,
    reference_order: "Order | None" = None,
    reference_payment: "Payment | None" = None,
    notes: str | None = None,
) -> "CreditTransaction":
    """Reduce debt created by a credit purchase."""
    paid_amount = pay_debt(
        client=client,
        amount=amount,
        transaction_type="purchase_reversal",
        user=user,
        reference_order=reference_order,
        reference_payment=reference_payment,
        notes=notes or _build_reversal_note("Reversión de compra a crédito", reference_order),
    )
    if paid_amount != amount:
        raise ValueError("No se pudo revertir completo el crédito del pedido.")

    transaction = client.credit_transactions.filter(
        transaction_type="purchase_reversal",
        amount=amount,
        reference_order=reference_order,
        reference_payment=reference_payment,
    ).order_by("-created_at").first()
    if transaction is None:
        raise ValueError("No se encontró la transacción de reversión de crédito.")
    return transaction


@transaction.atomic
def reverse_credit_payment(
    client: "Client",
    amount: Decimal,
    user: "User | None" = None,
    reference_order: "Order | None" = None,
    reference_payment: "Payment | None" = None,
    notes: str | None = None,
) -> "CreditTransaction":
    """Restore debt that was reduced by a payment being cancelled."""
    transaction = add_debt(
        client=client,
        amount=amount,
        transaction_type="payment_reversal",
        user=user,
        reference_order=reference_order,
        reference_payment=reference_payment,
        notes=notes or _build_reversal_note("Reversión de pago de deuda", reference_order),
    )
    if transaction is None:
        raise ValueError("No se pudo crear la reversión de pago de deuda.")
    return transaction


def _build_reversal_note(prefix: str, reference_order: "Order | None") -> str:
    """Build a consistent note for reversal transactions."""
    if reference_order is None:
        return prefix
    return f"{prefix} - Pedido #{reference_order.id}"


@transaction.atomic
def update_credit_limit(
    client: "Client",
    new_limit: Decimal,
    user: "User | None" = None,
    notes: str | None = None,
) -> "CreditTransaction | None":
    """
    Update client's credit limit with transaction history.

    Args:
        client: Client to update credit limit for
        new_limit: New credit limit amount (must be non-negative)
        user: User performing the transaction
        notes: Additional notes

    Returns:
        CreditTransaction if limit changed, None if no change

    Raises:
        ValueError: If new_limit is negative
    """
    from clients.models import CreditTransaction

    if new_limit < 0:
        raise ValueError("Credit limit cannot be negative")

    if new_limit == client.credit_limit:
        return None  # No change needed

    # Store previous values
    debt_before = client.current_debt
    credit_limit_before = client.credit_limit

    # Update credit limit
    client.credit_limit = new_limit

    # Save client
    client.save(update_fields=["credit_limit", "updated_at"])

    # Create transaction record
    final_notes = (
        notes or f"Cambio de límite de crédito de ${credit_limit_before:.2f} a ${new_limit:.2f}"
    )
    return CreditTransaction.objects.create(
        client=client,
        transaction_type="limit_change",
        amount=abs(new_limit - credit_limit_before),
        debt_before=debt_before,
        debt_after=client.current_debt,
        credit_limit_before=credit_limit_before,
        credit_limit_after=new_limit,
        notes=final_notes,
        created_by=user,
    )


@transaction.atomic
def pay_debt_from_balance(
    client: "Client",
    amount: Decimal,
    user: "User | None" = None,
    reference_order: "Order | None" = None,
    reference_payment: "Payment | None" = None,
    notes: str | None = None,
) -> PaymentResult:
    """
    Pay client's debt using their available balance.

    Args:
        client: Client to process payment for
        amount: Amount to pay towards debt using balance (must be positive)
        user: User performing the transaction
        reference_order: Related order (if applicable)
        reference_payment: Related payment (if applicable)
        notes: Additional notes

    Returns:
        PaymentResult dict with success status and details
    """
    from clients.models import BalanceTransaction, CreditTransaction

    if amount <= 0:
        return {"success": False, "error": "Amount must be positive"}

    # Check if client has sufficient balance
    if client.balance < amount:
        return {
            "success": False,
            "error": f"Saldo insuficiente. Disponible: ${client.balance:.2f}, Requerido: ${amount:.2f}",
        }

    # Check if there's enough debt to pay
    if client.current_debt < amount:
        return {
            "success": False,
            "error": f"Monto excede la deuda actual. Deuda: ${client.current_debt:.2f}, "
            f"Intentando pagar: ${amount:.2f}",
        }

    # Calculate actual payment amount (limited by debt)
    payment_amount = min(amount, client.current_debt)

    # Store previous values for both balance and debt
    balance_before = client.balance
    debt_before = client.current_debt

    # Update both balance and debt
    client.balance -= payment_amount
    client.current_debt -= payment_amount

    # Save client
    client.save(update_fields=["balance", "current_debt", "updated_at"])

    # Create balance transaction (deduction)
    balance_notes = notes or f"Pago de deuda con saldo - ${payment_amount:.2f}"
    BalanceTransaction.objects.create(
        client=client,
        transaction_type="payment",
        amount=payment_amount,
        balance_before=balance_before,
        balance_after=client.balance,
        notes=f"[PAGO DEUDA] {balance_notes}",
        reference_order=reference_order,
        reference_payment=reference_payment,
        created_by=user,
    )

    # Create credit transaction (debt reduction)
    credit_notes = notes or f"Pago con saldo - ${payment_amount:.2f}"
    CreditTransaction.objects.create(
        client=client,
        transaction_type="payment_from_balance",
        amount=payment_amount,
        debt_before=debt_before,
        debt_after=client.current_debt,
        credit_limit_before=client.credit_limit,
        credit_limit_after=client.credit_limit,
        notes=f"[PAGO CON SALDO] {credit_notes}",
        reference_order=reference_order,
        reference_payment=reference_payment,
        created_by=user,
    )

    return {
        "success": True,
        "amount_paid": payment_amount,
        "remaining_balance": client.balance,
        "remaining_debt": client.current_debt,
        "available_credit": client.get_available_credit(),
    }


@transaction.atomic
def transfer_balance(
    from_client: "Client",
    to_client: "Client",
    amount: Decimal,
    user: "User | None" = None,
    notes: str | None = None,
) -> TransferResult:
    """
    Transfer balance from one client to another.

    Args:
        from_client: Client to transfer balance from
        to_client: Client to transfer balance to
        amount: Amount to transfer (must be positive)
        user: User performing the transfer
        notes: Additional notes

    Returns:
        TransferResult dict with success status and details
    """
    if amount <= 0:
        return {"success": False, "error": "Amount must be positive"}

    if from_client.balance < amount:
        return {
            "success": False,
            "error": f"Insufficient balance. Available: ${from_client.balance:.2f}, "
            f"Required: ${amount:.2f}",
        }

    # Deduct from source client
    transfer_notes = notes or f"Transferencia a {to_client.name}"
    deduct_result = deduct_balance(
        client=from_client,
        amount=amount,
        transaction_type="transfer_out",
        user=user,
        transfer_to_client=to_client,
        notes=transfer_notes,
    )

    if not deduct_result:
        return {"success": False, "error": "Failed to deduct from source account"}

    # Add to target client
    receive_notes = notes or f"Transferencia de {from_client.name}"
    add_balance(
        client=to_client,
        amount=amount,
        transaction_type="transfer_in",
        user=user,
        transfer_to_client=from_client,
        notes=receive_notes,
    )

    return {
        "success": True,
        "amount_transferred": amount,
        "source_balance": from_client.balance,
        "target_balance": to_client.balance,
    }


def get_financial_summary(
    client: "Client",
    start_date=None,
    end_date=None,
) -> FinancialSummary:
    """
    Get comprehensive financial summary for the client.

    Orchestrates both BalanceTransaction and CreditTransaction managers
    to provide a complete financial picture.

    Args:
        client: Client to get summary for
        start_date: Filter transactions after this date
        end_date: Filter transactions before this date

    Returns:
        FinancialSummary dict with financial data
    """
    from clients.models import BalanceTransaction, CreditTransaction

    # Get balance summary using manager
    balance_qs = BalanceTransaction.objects.for_client(client)
    if start_date or end_date:
        balance_qs = balance_qs.in_date_range(start_date, end_date)
    balance_summary = balance_qs.aggregate_summary()

    # Get credit summary using manager
    credit_qs = CreditTransaction.objects.for_client(client)
    if start_date or end_date:
        credit_qs = credit_qs.in_date_range(start_date, end_date)
    credit_summary = credit_qs.aggregate_summary()

    return {
        "current_balance": client.balance,
        "current_debt": client.current_debt,
        "credit_limit": client.credit_limit,
        "available_credit": client.get_available_credit(),
        "balance_summary": balance_summary,
        "credit_summary": credit_summary,
        "period_start": start_date,
        "period_end": end_date,
    }
