from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from enum import Enum
from django.utils import timezone

from product.models import UNIT_CHOICES

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

ORDER_TYPE_CHOICES = (
    ('contado', 'Contado'),
    ('credito', 'Credito'),
    # Agrega más tipos según sea necesario
)

class OrderQuerySet(models.QuerySet):
    """Custom queryset for Order model with common filters"""

    def unbilled(self):
        """
        Get orders that haven't been added to any billing record.

        Returns:
            QuerySet of unbilled orders
        """
        return self.filter(invoice_links__isnull=True).distinct()

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
        # Billable orders must be completed and not linked to another invoice.
        # When editing, keep the currently linked order selectable even if it no
        # longer matches the billable filters.
        billable_filter = Q(
            status=OrderStatus.COMPLETED.value,
            invoice_links__isnull=True,
        )

        if exclude_order_id:
            qs = self.for_client(client).filter(
                billable_filter | Q(pk=exclude_order_id)
            )
        else:
            qs = self.for_client(client).filter(billable_filter)

        return qs.distinct().order_by('-order_date')

    def today_orders(self, user=None):
        """
        Get orders from today, optionally filtered by user.

        Args:
            user: Optional User instance to filter by. If provided and user is not staff,
                  only returns orders created by that user.

        Returns:
            QuerySet of today's orders with optimized prefetch/select_related
        """
        today = timezone.now().date()
        qs = self.filter(order_date__date=today).select_related(
            'client', 'owner'
        ).prefetch_related('items', 'payments')

        if user and not user.is_staff:
            qs = qs.filter(owner=user)

        return qs

    def with_payment_totals(self) -> 'OrderQuerySet':
        """Annotate each order with the sum of its completed payments as `total_paid`."""
        from payment.models import Payment

        paid_subquery = (
            Payment.objects.filter(order=OuterRef('pk'), status='completed')
            .values('order')
            .annotate(total=Sum('amount'))
            .values('total')
        )
        return self.annotate(
            total_paid=Coalesce(
                Subquery(paid_subquery, output_field=DecimalField()),
                Value(Decimal('0'), output_field=DecimalField()),
            )
        )

    def paid(self) -> 'OrderQuerySet':
        """Filter orders where total completed payments >= total_amount."""
        return self.with_payment_totals().filter(total_paid__gte=F('total_amount'))

    def unpaid(self) -> 'OrderQuerySet':
        """Filter orders where total completed payments < total_amount."""
        return self.with_payment_totals().filter(total_paid__lt=F('total_amount'))


class OrderManager(models.Manager):
    """Custom manager for Order model"""

    def get_queryset(self):
        return OrderQuerySet(self.model, using=self._db).filter(deleted_at=None)

    def unbilled(self):
        return self.get_queryset().unbilled()

    def for_client(self, client):
        return self.get_queryset().for_client(client)

    def unbilled_for_client(self, client, exclude_order_id=None):
        return self.get_queryset().unbilled_for_client(client, exclude_order_id)

    def today_orders(self, user=None):
        return self.get_queryset().today_orders(user)

    def with_payment_totals(self):
        return self.get_queryset().with_payment_totals()

    def paid(self):
        return self.get_queryset().paid()

    def unpaid(self):
        return self.get_queryset().unpaid()


# Create your models here.
class Order(TimeStampedModel):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='orders')
    order_date = models.DateTimeField(auto_now_add=True, db_index=True)
    subtotal_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Subtotal", help_text="Suma de los productos antes de descuentos")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    cantidad_cobrada = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Cantidad Cobrada", help_text="Cantidad realmente cobrada al cliente (puede ser mayor al total para agregar saldo)")
    status = models.CharField(max_length=50, choices=ORDER_STATUS_CHOICES, default=OrderStatus.PENDING.value, db_index=True)
    notes = models.TextField(blank=True, null=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Empleado", help_text="Empleado que creó la orden")
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Descuento", help_text="Descuento aplicado a la orden (en la moneda del total)")
    type = models.CharField(max_length=50, default='contado', null=True, blank=True, choices=ORDER_TYPE_CHOICES, verbose_name="Tipo de Orden", help_text="Tipo de orden para diferenciar entre órdenes a credito y órdenes de contado")
    objects = OrderManager()

    class Meta:
        ordering = ['-order_date']
        verbose_name = 'Pedido'
        verbose_name_plural = 'Pedidos'
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
    
    @property
    def total_paid(self) -> Decimal:
        """Sum of all completed payments. Uses prefetch cache when available."""
        if hasattr(self, '_annotated_total_paid'):
            return self._annotated_total_paid
        return sum(
            (p.amount for p in self.payments.all() if p.status == 'completed'),
            Decimal('0'),
        )

    @total_paid.setter
    def total_paid(self, value):
        self._annotated_total_paid = value

    @property
    def is_paid(self) -> bool:
        """True when total completed payments cover the order total."""
        return self.total_paid >= self.total_amount
    
    @property
    def is_closed(self) -> bool:
        """True when the order is completed and paid."""
        return self.status == OrderStatus.COMPLETED.value and self.is_paid

    def __str__(self):
        return f"{self.client.name} - Pedido #{self.id} - {self.get_status_display()} (${self.total_amount})"

class OrderProduct(TimeStampedModel):
    order = models.ForeignKey('Order', related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey('product.Product', on_delete=models.PROTECT, related_name='order_products')
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.TextField(blank=True, null=True)
    def __str__(self):
        return f"{self.quantity} x {self.product.name} {self.product.presentation} {UNIT_CHOICES[self.product.unit_of_measure][1]}"
    def get_total_price(self):
        return self.quantity * self.unit_price


class OrderSplit(TimeStampedModel):
    """Track order split operations for reporting purposes"""
    source_order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='split_as_source', verbose_name="Orden Original")
    child_order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='split_as_child', verbose_name="Orden Derivada")
    split_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="Dividido por")
    
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