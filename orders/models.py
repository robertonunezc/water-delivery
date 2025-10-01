from django.db import models
from enum import Enum

from core.models import TimeStampedModel

class OrderStatus(Enum):
    PENDING = 'PENDING'
    COMPLETED = 'COMPLETED'
    CANCELLED = 'CANCELLED'

ORDER_STATUS_CHOICES = (
    (OrderStatus.PENDING.value, 'Pendiente'),
    (OrderStatus.COMPLETED.value, 'Completado'),
    (OrderStatus.CANCELLED.value, 'Cancelado'),
)

# Create your models here.
class Order(TimeStampedModel):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='orders')
    order_date = models.DateTimeField(auto_now_add=True, db_index=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, choices=ORDER_STATUS_CHOICES, default='PENDING', db_index=True)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-order_date']
        verbose_name = 'Orden'
        verbose_name_plural = 'Órdenes'
        indexes = [
            models.Index(fields=['order_date'], name='orders_order_date_idx'),
            models.Index(fields=['status'], name='orders_order_status_idx'),
            models.Index(fields=['client', 'status'], name='orders_client_status_idx'),
            models.Index(fields=['order_date', 'status'], name='orders_date_status_idx'),
        ]
    
    def __str__(self):
        return f"Order {self.id} for {self.client.name} - {self.status} ({self.total_amount})"

class OrderProduct(models.Model):
    order = models.ForeignKey('Order', related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey('product.Product', on_delete=models.PROTECT, related_name='order_products')
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.TextField(blank=True, null=True)
    def __str__(self):
        return f"{self.quantity} x {self.product.name} @ {self.unit_price}"
    def get_total_price(self):
        return self.quantity * self.unit_price