from django.db import models
from django.db.models import Q
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


class OrderQuerySet(models.QuerySet):
    """Custom queryset for Order model with common filters"""

    def unbilled(self):
        """
        Get orders that haven't been added to any billing record.

        Returns:
            QuerySet of unbilled orders
        """
        return self.filter(billing_orders__isnull=True).distinct()

    def for_client(self, client):
        """
        Filter orders for a specific client.

        Args:
            client: Client instance or client ID

        Returns:
            QuerySet filtered by client
        """
        if hasattr(client, 'pk'):
            return self.filter(client=client)
        return self.filter(client_id=client)

    def unbilled_for_client(self, client, exclude_order_id=None):
        """
        Get unbilled orders for a specific client.

        Args:
            client: Client instance or client ID
            exclude_order_id: Optional order ID to exclude (for editing existing records)

        Returns:
            QuerySet of unbilled orders for the client
        """
        qs = self.for_client(client).unbilled()

        if exclude_order_id:
            # Include the current order if we're editing an existing billing order
            qs = qs | self.filter(pk=exclude_order_id)
            qs = qs.distinct()

        return qs.order_by('-order_date')


class OrderManager(models.Manager):
    """Custom manager for Order model"""

    def get_queryset(self):
        return OrderQuerySet(self.model, using=self._db)

    def unbilled(self):
        return self.get_queryset().unbilled()

    def for_client(self, client):
        return self.get_queryset().for_client(client)

    def unbilled_for_client(self, client, exclude_order_id=None):
        return self.get_queryset().unbilled_for_client(client, exclude_order_id)


# Create your models here.
class Order(TimeStampedModel):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='orders')
    order_date = models.DateTimeField(auto_now_add=True, db_index=True)
    subtotal_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Subtotal", help_text="Suma de los productos antes de descuentos")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    cantidad_cobrada = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Cantidad Cobrada", help_text="Cantidad realmente cobrada al cliente (puede ser mayor al total para agregar saldo)")
    status = models.CharField(max_length=50, choices=ORDER_STATUS_CHOICES, default=OrderStatus.PENDING.value, db_index=True)
    notes = models.TextField(blank=True, null=True)
    owner = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Empleado", help_text="Empleado que creó la orden")
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Descuento", help_text="Descuento aplicado a la orden (en la moneda del total)")
    # Custom manager
    objects = OrderManager()

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
    
    def get_status_display_fixed(self):
        """
        Helper method - now just an alias to get_status_display() since status values are fixed.
        Kept for backward compatibility with existing templates.
        """
        return self.get_status_display()
    
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


class OrderSplit(TimeStampedModel):
    """Track order split operations for reporting purposes"""
    source_order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='split_as_source', verbose_name="Orden Original")
    child_order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='split_as_child', verbose_name="Orden Derivada")
    split_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, verbose_name="Dividido por")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'División de Orden'
        verbose_name_plural = 'Divisiones de Órdenes'
        indexes = [
            models.Index(fields=['source_order'], name='ordersplit_source_idx'),
            models.Index(fields=['child_order'], name='ordersplit_child_idx'),
        ]
    
    def __str__(self):
        return f"Split: Order #{self.source_order.id} → Order #{self.child_order.id}"