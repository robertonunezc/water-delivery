from django.db import models

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
class Payment(models.Model):
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
            # For credit payments, validate client has available credit
            if not self.pk:  # Only validate on creation, not updates
                available_credit = self.client.get_available_credit()
                if available_credit < self.amount:
                    raise ValidationError(
                        f"Cliente no tiene suficiente crédito disponible. "
                        f"Crédito disponible: ${available_credit:.2f}, "
                        f"Monto requerido: ${self.amount:.2f}"
                    )
    
    def save(self, *args, **kwargs):
        """Custom save method to handle balance and credit payments"""
        is_new_payment = self.pk is None
        
        if is_new_payment and self.status == 'completed':
            # Process payment based on method
            if self.method == 'balance':
                # Deduct from client balance
                success = self.client.deduct_balance(
                    amount=self.amount,
                    transaction_type='payment',
                    description=f'Pago de orden #{self.order.id if self.order else "N/A"} con saldo',
                    user=self.created_by,
                    reference_order=self.order,
                    reference_payment=None  # Will be set after save
                )
                if not success:
                    from django.core.exceptions import ValidationError
                    raise ValidationError("NO cuenta con saldo suficiente para el pago")
                self.balance_used = self.amount
                
            elif self.method == 'credit':
                # Add to client debt
                success = self.client.add_debt(
                    amount=self.amount,
                    transaction_type='purchase',
                    description=f'Compra orden #{self.order.id if self.order else "N/A"} a crédito',
                    user=self.created_by,
                    reference_order=self.order,
                    reference_payment=None  # Will be set after save
                )
                if not success:
                    from django.core.exceptions import ValidationError
                    raise ValidationError("NO cuenta con límite de crédito suficiente para el pago")
                self.credit_used = self.amount
        
        super().save(*args, **kwargs)
        
        # Update transaction records with payment reference after save
        if is_new_payment and self.status == 'completed':
            if self.method == 'balance' and self.pk:
                # Update the balance transaction with payment reference
                balance_tx = self.client.balance_transactions.filter(
                    reference_order=self.order,
                    amount=self.amount,
                    transaction_type='payment',
                    reference_payment__isnull=True
                ).first()
                if balance_tx:
                    balance_tx.reference_payment = self
                    balance_tx.save()
                    
            elif self.method == 'credit' and self.pk:
                # Update the credit transaction with payment reference
                credit_tx = self.client.credit_transactions.filter(
                    reference_order=self.order,
                    amount=self.amount,
                    transaction_type='purchase',
                    reference_payment__isnull=True
                ).first()
                if credit_tx:
                    credit_tx.reference_payment = self
                    credit_tx.save()
    
    def reverse_payment(self, user=None, reason=''):
        """Reverse the payment by restoring balance or reducing debt"""
        if self.status != 'completed':
            return False
            
        if self.method == 'balance' and self.balance_used > 0:
            # Restore balance to client
            self.client.add_balance(
                amount=self.balance_used,
                transaction_type='refund',
                description=f'Reversión de pago #{self.id} - {reason}',
                user=user,
                reference_order=self.order,
                reference_payment=self,
                notes=f'Reversión de pago original de ${self.balance_used:.2f}'
            )
            self.balance_used = 0
            
        elif self.method == 'credit' and self.credit_used > 0:
            # Reduce client debt
            self.client.pay_debt(
                amount=self.credit_used,
                transaction_type='adjustment',
                description=f'Reversión de compra a crédito #{self.id} - {reason}',
                user=user,
                reference_order=self.order,
                reference_payment=self,
                notes=f'Reversión de compra a crédito original de ${self.credit_used:.2f}'
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