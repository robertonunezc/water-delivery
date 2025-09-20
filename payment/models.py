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
class Payment(models.Model):
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES)
    client = models.ForeignKey('clients.Client', related_name='payments', on_delete=models.PROTECT)
    order = models.ForeignKey('orders.Order', related_name='payments', on_delete=models.PROTECT)
    def __str__(self):
        return f"Payment of {self.amount} on {self.date}"