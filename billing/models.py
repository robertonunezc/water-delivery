from django.db import models
from django.forms import ValidationError

from core.models import TimeStampedModel

# Create your models here.
class BillingRecord(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='billing_records', verbose_name='Cliente')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto")
    identifier = models.CharField(max_length=100, unique=True, verbose_name="Serie")
    folio = models.CharField(max_length=100, unique=True, verbose_name="Folio")
    date = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)
    file = models.FileField(upload_to='billing_files/', blank=True, null=True)
    emmited_at = models.DateTimeField(blank=True, null=True, verbose_name="Fecha de emisión")
    def __str__(self):
        return f"Factura Emitida #{self.id} para {self.client.name} - {self.amount}"
    class Meta:
        ordering = ['-date']
        verbose_name = 'Facturación'
        verbose_name_plural = 'Facturas Emitidas'
    # def clean(self):
    #     # Check if there is a billing record from this client without billing orders
    #     if self.pk is None:  # Only check for new records
    #         existing_records = BillingRecord.objects.filter(client=self.client)
    #         for record in existing_records:
    #             if not record.billing_orders.exists():
    #                 raise ValidationError(f"El cliente {self.client.name} ya tiene un registro de facturación sin ventas asociadas (ID: {record.id}). Por favor, complete ese registro antes de crear uno nuevo.")
class BillingOrder(TimeStampedModel):
    billing_record = models.ForeignKey('billing.BillingRecord', on_delete=models.CASCADE, related_name='billing_orders', verbose_name='Registro de Facturación')
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='billing_orders', verbose_name='Venta')
    is_paid = models.BooleanField(default=False, verbose_name='Pagado Totalmente')
    partially_paid = models.BooleanField(default=False, verbose_name='Pago parcial')

    def __str__(self):
        return f"Agregar venta a factura #{self.id} para Pedido {self.order.id} - Pagado: {self.is_paid}"
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Agregar venta a factura'
        verbose_name_plural = 'Agregar ventas a factura'
