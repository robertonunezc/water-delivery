from django.conf import settings
from django.db import models
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
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Creado por")
    
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
        should_apply_accounting = apply_accounting and is_new_payment and self.status == 'completed'

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
        ]
