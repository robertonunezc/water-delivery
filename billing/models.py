from django.db import models

# Create your models here.
class BillingRecord(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    identifier = models.CharField(max_length=100, unique=True, verbose_name="Identificador de Factura")
    date = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)
    file = models.FileField(upload_to='billing_files/', blank=True, null=True)
    def __str__(self):
        return f"Factura Emitida #{self.id} para {self.client.name} - {self.amount}"
    class Meta:
        ordering = ['-date']
        verbose_name = 'Facturación'
        verbose_name_plural = 'Facturas Emitidas'

class BillingOrder(models.Model):
    billing_record = models.ForeignKey('billing.BillingRecord', on_delete=models.CASCADE)
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='billing_orders', verbose_name='Venta')
    is_paid = models.BooleanField(default=False, verbose_name='Pagado Totalmente')
    partially_paid = models.BooleanField(default=False, verbose_name='Pago parcial')
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Monto pagado')
    payment_date = models.DateTimeField(blank=True, null=True, verbose_name='Fecha de pago')

    def __str__(self):
        return f"Agregar venta a factura #{self.id} para Pedido {self.order.id} - Pagado: {self.is_paid}"
    class Meta:
        ordering = ['-payment_date']
        verbose_name = 'Agregar venta a factura'
        verbose_name_plural = 'Agregar ventas a factura'
