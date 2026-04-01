from django.db import models
from core.models import TimeStampedModel

# Create your models here.

PAYMENT_METHOD_CHOICES = [
    ('credit_card', 'Tarjeta de Crédito'),
    ('debit_card', 'Tarjeta de Débito'),
    ('cash', 'Efectivo'),
    ('balance', 'Saldo'),
    ('paypal', 'PayPal'),
    ('credit', 'Crédito'),
    ('bank_transfer', 'Transferencia Bancaria'),
]
PAYMENT_STATUS_CHOICES = [
    ('completed', 'Completado'),
    ('pending', 'Pendiente'),
    ('failed', 'Fallido'),
]
class Payment(TimeStampedModel):
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto del Pago")
    date = models.DateTimeField(auto_now_add=True, verbose_name="Fecha")
    method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, verbose_name="Método de Pago")
    client = models.ForeignKey('clients.Client', related_name='payments', on_delete=models.PROTECT, verbose_name="Cliente")
    order = models.ForeignKey('orders.Order', related_name='payments', on_delete=models.PROTECT, verbose_name="Orden")
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='completed', verbose_name="Estado del Pago")  # e.g., completed, pending, failed
    
    # Track how the payment was processed for balance/credit payments
    balance_used = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Saldo Utilizado", help_text="Monto pagado usando saldo del cliente")
    credit_used = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Crédito Utilizado", help_text="Monto pagado usando crédito del cliente")
    
    # Audit field
    created_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Creado por")
    
    # Temporary field to hold credit note during payment processing (not stored in DB)
    _credit_note = None
    def status_display(self):
        return dict(PAYMENT_STATUS_CHOICES).get(self.status, 'Desconocido')
    def get_method_display(self):
        return dict(PAYMENT_METHOD_CHOICES).get(self.method, 'Desconocido')
    def clean(self):
        """Validate payment before saving"""
        from django.core.exceptions import ValidationError
        
        if self.method == 'balance':
            # For balance payments, validate client has sufficient balance
            if not self.pk:  # Only validate on creation, not updates
                if self.client.balance < self.amount:
                    raise ValidationError(
                        f"Cliente no tiene suficiente saldo. "
                        f"Saldo disponible: ${self.client.balance:.2f}, "
                        f"Monto requerido: ${self.amount:.2f}"
                    )
        
        elif self.method == 'credit':
            # For credit payments, use client's validation method
            if not self.pk:  # Only validate on creation, not updates
                # Note: We can't validate the note requirement here since we don't have access to it
                # The note validation should be done at the view level before creating the payment
                if not self.client.can_use_credit_for_payment():
                    raise ValidationError(
                        "Este cliente no puede usar crédito para pagos en este momento."
                    )
                
                # For clients that can pay with credit, allow payments even if they exceed the credit limit
                # This enables negative credit balances when necessary
                available_credit = self.client.get_available_credit()
                if available_credit < self.amount:
                    # Log a warning but allow the payment to proceed
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        f'Payment {self.amount} for client {self.client.id} ({self.client.name}) '
                        f'exceeds available credit of ${available_credit:.2f}. '
                        f'This will result in exceeding credit limit.'
                    )

    def apply_accounting_side_effects(self):
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
                user=self.created_by,
                reference_order=self.order,
                reference_payment=None,
                notes=f'Pago de orden #{self.order.id if self.order else "N/A"} con saldo'
            )
            if not result:
                raise ValidationError("NO cuenta con saldo suficiente para el pago")
            self.balance_used = self.amount

        elif self.method == 'credit':
            credit_note = getattr(self, '_credit_note', None)
            notes_text = f'Compra orden #{self.order.id if self.order else "N/A"} a crédito'
            if credit_note:
                notes_text += f'. {credit_note}'
            result = balance_service.add_debt(
                client=self.client,
                amount=self.amount,
                transaction_type='purchase',
                user=self.created_by,
                reference_order=self.order,
                reference_payment=None,
                notes=notes_text
            )
            if not result:
                available_credit = self.client.get_available_credit()
                can_use_credit = self.client.can_pay_with_credit
                raise ValidationError(
                    f"No se puede procesar el pago con crédito. "
                    f"Cliente puede usar crédito: {can_use_credit}, "
                    f"Crédito disponible: ${available_credit:.2f}, "
                    f"Monto requerido: ${self.amount:.2f}"
                )
            self.credit_used = self.amount

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

        elif self.method == 'credit':
            credit_tx = self.client.credit_transactions.filter(
                reference_order=self.order,
                amount=self.amount,
                transaction_type='purchase',
                reference_payment__isnull=True
            ).first()
            if credit_tx:
                credit_tx.reference_payment = self
                credit_tx.save()
    
    def save(self, *args, **kwargs):
        """Custom save method to handle balance and credit payments"""
        apply_accounting = kwargs.pop('apply_accounting', True)

        is_new_payment = self.pk is None
        should_apply_accounting = apply_accounting and is_new_payment and self.status == 'completed'

        if should_apply_accounting:
            self.apply_accounting_side_effects()

        super().save(*args, **kwargs)
        
        # Update transaction records with payment reference after save
        if should_apply_accounting:
            self.link_pending_transaction_references()
    
    def reverse_payment(self, user=None, reason=''):
        """Reverse the payment by restoring balance or reducing debt"""
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

        elif self.method == 'credit' and self.credit_used > 0:
            # Reduce client debt
            balance_service.pay_debt(
                client=self.client,
                amount=self.credit_used,
                transaction_type='adjustment',
                user=user,
                reference_order=self.order,
                reference_payment=self,
                notes=f'Reversión de compra a crédito #{self.id} - {reason}'
            )
            self.credit_used = 0

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
        
        if self.method not in ['balance', 'credit']:
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
        ]