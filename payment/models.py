from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Case, DecimalField, F, Q, Value, When
from core.models import TimeStampedModel

# Create your models here.

PAYMENT_METHOD_CHOICES = [
    ('credit_card', 'Tarjeta de Crédito'),
    ('debit_card', 'Tarjeta de Débito'),
    ('cash', 'Efectivo'),
    ('balance', 'Saldo'),
    ('paypal', 'PayPal'),
    ('pending_credit', 'Crédito Pendiente'),
    ('bank_transfer', 'Transferencia Bancaria'),
]
PAYMENT_STATUS_CHOICES = [
    ('completed', 'Completado'),
    ('pending', 'Pendiente'),
    ('failed', 'Fallido'),
    ('reversed', 'Revertido'),
]
PAYMENT_ENTRY_KIND_PAYMENT = 'payment'
PAYMENT_ENTRY_KIND_REVERSAL = 'reversal'
PAYMENT_ENTRY_KIND_CHOICES = [
    (PAYMENT_ENTRY_KIND_PAYMENT, 'Pago'),
    (PAYMENT_ENTRY_KIND_REVERSAL, 'Reversión'),
]


class PaymentCollection(TimeStampedModel):
    """Groups receipts from a single collection event and any excess balance deposit."""

    payer = models.ForeignKey(
        'clients.Client',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='payment_collections',
        verbose_name="Pagador",
    )
    excess_balance_transaction = models.OneToOneField(
        'clients.BalanceTransaction',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='excess_for_collection',
        verbose_name="Excedente abonado a saldo",
    )
    excess_reversal_transaction = models.OneToOneField(
        'clients.BalanceTransaction',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='excess_reversal_for_collection',
        verbose_name="Reversión de excedente",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Creado por",
    )
    notes = models.TextField(blank=True, default='', verbose_name="Notas")

    class Meta:
        verbose_name = 'Cobro'
        verbose_name_plural = 'Cobros'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Cobro #{self.pk}"


class PaymentQuerySet(models.QuerySet):
    """Custom queryset for payment financial events, receipts, and reversals."""

    @staticmethod
    def signed_amount_expression() -> Case:
        """Return SQL expression for signed monetary contribution of each row."""
        real_event = ~Q(method='pending_credit') & Q(status='completed')
        return Case(
            When(
                real_event & Q(entry_kind=PAYMENT_ENTRY_KIND_PAYMENT),
                then=F('amount'),
            ),
            When(
                real_event & Q(entry_kind=PAYMENT_ENTRY_KIND_REVERSAL),
                then=-F('amount'),
            ),
            default=Value(Decimal('0.00')),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )

    def with_signed_amount(self) -> 'PaymentQuerySet':
        """Annotate each payment row with its signed net contribution."""
        return self.annotate(net_amount=self.signed_amount_expression())

    def financial_events(self) -> 'PaymentQuerySet':
        """Return real payment receipts and reversals (excludes credit markers)."""
        return self.exclude(method='pending_credit')

    def effective_receipts(self) -> 'PaymentQuerySet':
        """Return completed real payment receipts (excludes reversals and credit markers)."""
        return self.filter(
            entry_kind=PAYMENT_ENTRY_KIND_PAYMENT,
            status='completed',
        ).exclude(method='pending_credit')

    def reversible_receipts(self) -> 'PaymentQuerySet':
        """Return effective receipts that do not yet have a reversal entry."""
        return self.effective_receipts().filter(reversal_entry__isnull=True)

    def reversals(self) -> 'PaymentQuerySet':
        """Return only reversal entries."""
        return self.filter(entry_kind=PAYMENT_ENTRY_KIND_REVERSAL)

    def not_reversed(self) -> 'PaymentQuerySet':
        """Return payments that do not have legacy status='reversed'."""
        return self.exclude(status='reversed')

    def reversed(self) -> 'PaymentQuerySet':
        """Return only payments with legacy status='reversed'."""
        return self.filter(status='reversed')


class PaymentManager(models.Manager):
    """Default payment manager excluding soft-deleted rows."""

    def get_queryset(self) -> PaymentQuerySet:
        return PaymentQuerySet(self.model, using=self._db).filter(deleted_at=None)

    def financial_events(self) -> PaymentQuerySet:
        return self.get_queryset().financial_events()

    def effective_receipts(self) -> PaymentQuerySet:
        return self.get_queryset().effective_receipts()

    def reversible_receipts(self) -> PaymentQuerySet:
        return self.get_queryset().reversible_receipts()

    def reversals(self) -> PaymentQuerySet:
        return self.get_queryset().reversals()

    def not_reversed(self) -> PaymentQuerySet:
        return self.get_queryset().not_reversed()

    def reversed(self) -> PaymentQuerySet:
        return self.get_queryset().reversed()


class Payment(TimeStampedModel):
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto del Pago")
    date = models.DateTimeField(auto_now_add=True, verbose_name="Fecha")
    method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, verbose_name="Método de Pago")
    client = models.ForeignKey('clients.Client', related_name='payments', on_delete=models.PROTECT, verbose_name="Cliente")
    order = models.ForeignKey('orders.Order', related_name='payments', on_delete=models.PROTECT, verbose_name="Orden")
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='completed', verbose_name="Estado del Pago")  # e.g., completed, pending, failed
    entry_kind = models.CharField(
        max_length=20,
        choices=PAYMENT_ENTRY_KIND_CHOICES,
        default=PAYMENT_ENTRY_KIND_PAYMENT,
        db_index=True,
        verbose_name="Tipo de Movimiento",
    )
    reversal_of = models.OneToOneField(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='reversal_entry',
        verbose_name="Reversión de",
    )
    collection = models.ForeignKey(
        PaymentCollection,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name="Cobro",
    )
    reversal_reason = models.TextField(blank=True, default='', verbose_name="Motivo de Reversión")

    # Track how the payment was processed for balance/credit payments
    balance_used = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Saldo Utilizado", help_text="Monto pagado usando saldo del cliente")
    credit_used = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Crédito Utilizado", help_text="Monto pagado usando crédito del cliente")
    
    # Audit field
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Creado por")
    objects = PaymentManager()

    @property
    def is_reversal(self) -> bool:
        return self.entry_kind == PAYMENT_ENTRY_KIND_REVERSAL

    @property
    def is_real_payment(self) -> bool:
        return (
            self.entry_kind == PAYMENT_ENTRY_KIND_PAYMENT
            and self.method != 'pending_credit'
        )

    @property
    def signed_amount(self) -> Decimal:
        """Signed monetary contribution (+amount for receipt, -amount for reversal, 0 otherwise)."""
        if self.status != 'completed' or self.method == 'pending_credit':
            return Decimal('0.00')
        magnitude = Decimal(str(self.amount))
        if self.entry_kind == PAYMENT_ENTRY_KIND_REVERSAL:
            return -magnitude
        return magnitude

    @property
    def has_reversal(self) -> bool:
        """True when an append-only reversal entry exists for this payment."""
        try:
            return self.reversal_entry is not None
        except Payment.DoesNotExist:
            return False

    def status_display(self):
        return dict(PAYMENT_STATUS_CHOICES).get(self.status, 'Desconocido')
    def get_method_display(self):
        return dict(PAYMENT_METHOD_CHOICES).get(self.method, 'Desconocido')
    def clean(self):
        """Validate payment before saving"""
        from django.core.exceptions import ValidationError

        if self.entry_kind == PAYMENT_ENTRY_KIND_REVERSAL:
            if not self.reversal_of_id:
                raise ValidationError("Una reversión debe referenciar el pago original.")
            if self.reversal_of and self.reversal_of.entry_kind != PAYMENT_ENTRY_KIND_PAYMENT:
                raise ValidationError("No se puede revertir una reversión.")
            return

        if self.reversal_of_id:
            raise ValidationError("Solo los movimientos de tipo reversión pueden referenciar un pago original.")

        if self.method == 'balance':
            # For balance payments, validate client has sufficient balance
            if not self.pk:  # Only validate on creation, not updates
                if self.client.balance < self.amount:
                    raise ValidationError(
                        f"Cliente no tiene suficiente saldo. "
                        f"Saldo disponible: ${self.client.balance:.2f}, "
                        f"Monto requerido: ${self.amount:.2f}"
                    )
        
    def apply_accounting_side_effects(self, transaction_date=None):
        """Apply financial mutations based on payment method."""
        from clients.services import balance_service
        from django.core.exceptions import ValidationError

        if self.status != 'completed':
            return

        if self.method == 'balance':
            result = balance_service.deduct_balance(
                client=self.client,
                amount=self.amount,
                transaction_type='payment',
                date=transaction_date,
                user=self.created_by,
                reference_order=self.order,
                reference_payment=None,
                notes=f'Pago de orden #{self.order.id if self.order else "N/A"} con saldo'
            )
            if not result:
                raise ValidationError("NO cuenta con saldo suficiente para el pago")
            self.balance_used = self.amount

    def link_pending_transaction_references(self):
        """Link balance/credit transactions created during accounting to this payment."""
        if not self.pk or self.status != 'completed':
            return

        if self.method == 'balance':
            balance_tx = self.client.balance_transactions.filter(
                reference_order=self.order,
                amount=self.amount,
                transaction_type='payment',
                reference_payment__isnull=True
            ).first()
            if balance_tx:
                balance_tx.reference_payment = self
                balance_tx.save()


    def save(self, *args, **kwargs):
        """Custom save method to handle payment accounting side effects."""
        apply_accounting = kwargs.pop('apply_accounting', True)

        is_new_payment = self.pk is None
        should_apply_accounting = (
            apply_accounting
            and is_new_payment
            and self.entry_kind == PAYMENT_ENTRY_KIND_PAYMENT
            and self.status == 'completed'
        )

        if should_apply_accounting:
            self.apply_accounting_side_effects()

        super().save(*args, **kwargs)
        
        # Update transaction records with payment reference after save
        if should_apply_accounting:
            self.link_pending_transaction_references()
    
    def reverse_payment(self, user=None, reason=''):
        """Reverse the payment by restoring balance when applicable."""
        from clients.services import balance_service

        if self.status != 'completed':
            return False

        if self.method == 'balance' and self.balance_used > 0:
            # Restore balance to client
            balance_service.add_balance(
                client=self.client,
                amount=self.balance_used,
                transaction_type='refund',
                user=user,
                reference_order=self.order,
                reference_payment=self,
                notes=f'Reversión de pago #{self.id} - {reason}'
            )
            self.balance_used = 0

        self.status = 'failed'
        self.save()
        return True
    
    def get_payment_breakdown(self):
        """Get detailed breakdown of how payment was processed"""
        breakdown = {
            'total_amount': self.amount,
            'method': self.get_method_display(),
            'balance_used': self.balance_used,
            'credit_used': self.credit_used,
            'cash_amount': 0
        }
        
        if self.method != 'balance':
            breakdown['cash_amount'] = self.amount
            
        return breakdown
    
    def __str__(self):
        return f"Payment of {self.amount} on {self.date}"
    class Meta:
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date'], name='payment_date_idx'),
            models.Index(fields=['client'], name='payment_client_idx'),
            models.Index(fields=['order'], name='payment_order_idx'),
            models.Index(fields=['status'], name='payment_status_idx'),
            models.Index(fields=['method'], name='payment_method_idx'),
            models.Index(fields=['entry_kind'], name='payment_entry_kind_idx'),
            models.Index(fields=['collection'], name='payment_collection_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        Q(entry_kind=PAYMENT_ENTRY_KIND_REVERSAL)
                        & Q(reversal_of__isnull=False)
                    )
                    | (
                        Q(entry_kind=PAYMENT_ENTRY_KIND_PAYMENT)
                        & Q(reversal_of__isnull=True)
                    )
                ),
                name='payment_reversal_of_matches_entry_kind',
            ),
        ]
