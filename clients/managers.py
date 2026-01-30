"""
Managers and QuerySets for clients app models.

Query logic lives with the model being queried - this provides composable,
reusable query methods.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Self

from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

if TYPE_CHECKING:
    from clients.models import Client


class BalanceTransactionQuerySet(models.QuerySet):
    """QuerySet for BalanceTransaction with composable query methods."""

    def for_client(self, client: "Client") -> Self:
        """Filter transactions for a specific client."""
        return self.filter(client=client)

    def in_date_range(
        self, start_date: date | datetime | None = None, end_date: date | datetime | None = None
    ) -> Self:
        """Filter transactions within a date range."""
        qs = self
        if start_date:
            qs = qs.filter(created_at__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__lte=end_date)
        return qs

    def last_n_days(self, days: int) -> Self:
        """Filter transactions from the last N days."""
        cutoff = timezone.now() - timedelta(days=days)
        return self.filter(created_at__gte=cutoff)

    def by_types(self, transaction_types: list[str]) -> Self:
        """Filter by specific transaction types."""
        return self.filter(transaction_type__in=transaction_types)

    def deposits(self) -> Self:
        """Filter to deposit-type transactions (money in)."""
        return self.by_types(["deposit", "refund", "transfer_in", "added_in_order"])

    def payments(self) -> Self:
        """Filter to payment-type transactions (money out)."""
        return self.by_types(["payment", "transfer_out"])

    def balance_at(self, target_date: date | datetime) -> Decimal:
        """
        Get client's balance at a specific date.

        Returns the balance_after from the last transaction at or before target_date.
        """
        last_transaction = (
            self.filter(created_at__lte=target_date).order_by("created_at").last()
        )
        if not last_transaction:
            return Decimal("0.00")
        return last_transaction.balance_after

    def aggregate_summary(self) -> dict:
        """
        Aggregate summary of balance transactions.

        Returns dict with total_deposits, total_payments, and transaction_count.
        """
        return {
            "total_deposits": self.deposits().aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00"),
            "total_payments": self.payments().aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00"),
            "transaction_count": self.count(),
        }


class BalanceTransactionManager(models.Manager):
    """Manager for BalanceTransaction using BalanceTransactionQuerySet."""

    def get_queryset(self) -> BalanceTransactionQuerySet:
        return BalanceTransactionQuerySet(self.model, using=self._db)

    def for_client(self, client: "Client") -> BalanceTransactionQuerySet:
        return self.get_queryset().for_client(client)


class CreditTransactionQuerySet(models.QuerySet):
    """QuerySet for CreditTransaction with composable query methods."""

    def for_client(self, client: "Client") -> Self:
        """Filter transactions for a specific client."""
        return self.filter(client=client)

    def in_date_range(
        self, start_date: date | datetime | None = None, end_date: date | datetime | None = None
    ) -> Self:
        """Filter transactions within a date range."""
        qs = self
        if start_date:
            qs = qs.filter(created_at__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__lte=end_date)
        return qs

    def last_n_days(self, days: int) -> Self:
        """Filter transactions from the last N days."""
        cutoff = timezone.now() - timedelta(days=days)
        return self.filter(created_at__gte=cutoff)

    def by_types(self, transaction_types: list[str]) -> Self:
        """Filter by specific transaction types."""
        return self.filter(transaction_type__in=transaction_types)

    def purchases(self) -> Self:
        """Filter to purchase-type transactions (debt increase)."""
        return self.by_types(["purchase", "interest", "fee"])

    def payments(self) -> Self:
        """Filter to payment-type transactions (debt decrease)."""
        return self.by_types(["payment", "payment_from_balance", "forgiveness"])

    def debt_at(self, target_date: date | datetime) -> Decimal:
        """
        Get client's debt at a specific date.

        Returns the debt_after from the last transaction at or before target_date.
        """
        last_transaction = (
            self.filter(created_at__lte=target_date).order_by("created_at").last()
        )
        if not last_transaction:
            return Decimal("0.00")
        return last_transaction.debt_after

    def aggregate_summary(self) -> dict:
        """
        Aggregate summary of credit transactions.

        Returns dict with total_purchases, total_payments, and transaction_count.
        """
        return {
            "total_purchases": self.purchases().aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00"),
            "total_payments": self.payments().aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00"),
            "transaction_count": self.count(),
        }


class CreditTransactionManager(models.Manager):
    """Manager for CreditTransaction using CreditTransactionQuerySet."""

    def get_queryset(self) -> CreditTransactionQuerySet:
        return CreditTransactionQuerySet(self.model, using=self._db)

    def for_client(self, client: "Client") -> CreditTransactionQuerySet:
        return self.get_queryset().for_client(client)
