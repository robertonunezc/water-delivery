from datetime import date, timedelta

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Prefetch, Q
from django.utils import timezone
from core.models import TimeStampedModel

from django.forms import ValidationError
WEEKDAY_TO_INDEX = {
    'monday': 0,
    'tuesday': 1,
    'wednesday': 2,
    'thursday': 3,
    'friday': 4,
    'saturday': 5,
    'sunday': 6,
}


class RouteClientQuerySet(models.QuerySet):
    def due_on(self, target_date: date):
        weekday = target_date.strftime('%A').lower()
        candidates = self.filter(is_active=True, route__weekday=weekday).select_related('route')
        due_ids = [route_client.pk for route_client in candidates if route_client.is_due_on(target_date)]
        return self.filter(pk__in=due_ids)

    def for_route(self, route: 'Route') -> 'RouteClientQuerySet':
        return self.filter(route=route, is_active=True)

    def search_by_client(self, query: str) -> 'RouteClientQuerySet':
        cleaned_query = query.strip()
        if not cleaned_query:
            return self

        return self.filter(
            Q(client__name__icontains=cleaned_query)
            | Q(client__addresses__street__icontains=cleaned_query)
            | Q(client__addresses__exterior_number__icontains=cleaned_query)
            | Q(client__addresses__locality__icontains=cleaned_query)
            | Q(client__addresses__zip_code__icontains=cleaned_query)
            | Q(client__contacts__name__icontains=cleaned_query)
            | Q(client__contacts__phone__icontains=cleaned_query)
        )

    def with_client_details(self) -> 'RouteClientQuerySet':
        return self.select_related('client').prefetch_related(
            'client__addresses',
            'client__contacts',
        )

    def with_client_products(self) -> 'RouteClientQuerySet':
        return self.prefetch_related('client__product_prices__product')

    def with_recent_client_orders(
        self,
        *,
        days: int = 30,
        to_attr: str = 'recent_orders',
    ) -> 'RouteClientQuerySet':
        from orders.models import Order

        since = timezone.now() - timedelta(days=days)
        recent_orders_queryset = (
            Order.objects.filter(created_at__gte=since)
            .select_related()
            .prefetch_related('items__product')
            .order_by('-created_at')
        )
        return self.prefetch_related(
            Prefetch(
                'client__orders',
                queryset=recent_orders_queryset,
                to_attr=to_attr,
            )
        )

    def ordered_for_detail(self) -> 'RouteClientQuerySet':
        return self.distinct().order_by('sequence')


class RouteClientManager(models.Manager.from_queryset(RouteClientQuerySet)):
    def get_queryset(self):
        return RouteClientQuerySet(self.model, using=self._db).filter(deleted_at=None)


# Create your models here.


class Route(TimeStampedModel):
    WEEKDAY_CHOICES = [
    ('monday', 'Lunes'),
    ('tuesday', 'Martes'),
    ('wednesday', 'Miércoles'),
    ('thursday', 'Jueves'),
    ('friday', 'Viernes'),
    ('saturday', 'Sábado'),
    ('sunday', 'Domingo'),
]
    name = models.CharField(max_length=100, verbose_name="Nombre de la Ruta")
    description = models.TextField(blank=True, null=True, verbose_name="Descripción")
    transportation = models.ForeignKey('core.Transport', related_name='routes', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Vehículo")
    weekday = models.CharField(max_length=10, choices=WEEKDAY_CHOICES, default='monday', verbose_name="Día de la Semana")
    is_active = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        verbose_name = 'Ruta'
        verbose_name_plural = 'Rutas'
        indexes = [
            models.Index(fields=['weekday'], name='routes_route_weekday_idx'),
            models.Index(fields=['is_active'], name='routes_route_active_idx'),
            models.Index(fields=['transportation', 'weekday'], name='routes_transport_weekday_idx'),
        ]

    def __str__(self):
        return f"{self.name} - {self.transportation} - {self.get_weekday_display()}"
    

    @classmethod
    def get_today_routes(cls, transportation=None):
        """Get routes for today's weekday"""
        today_weekday = date.today().strftime('%A').lower()
        routes = cls.objects.filter(weekday=today_weekday, is_active=True)
        if transportation:
            routes = routes.filter(transportation=transportation)
        return routes

class RouteClientOrder(TimeStampedModel):
    """Links a route with a client and their specific order for that day"""
    route = models.ForeignKey(Route, related_name='route_client_orders', on_delete=models.CASCADE)
    client = models.ForeignKey('clients.Client', related_name='client_route_orders', on_delete=models.CASCADE)
    order = models.ForeignKey('orders.Order', related_name='route_orders', on_delete=models.CASCADE)
    sequence = models.PositiveIntegerField(help_text="Order of visit in the route")
    visit_date = models.DateField(help_text="Specific date this order should be visited")
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        unique_together = ('route', 'client', 'visit_date')
        ordering = ['sequence']
        indexes = [
            models.Index(fields=['visit_date'], name='routes_clientorder_date_idx'),
            models.Index(fields=['is_completed'], name='routes_clientorder_comptd_idx'),
            models.Index(fields=['route', 'visit_date'], name='routes_route_date_idx'),
        ]

    def __str__(self):
        return f"{self.client} - {self.order} on {self.visit_date} (Route: {self.route.name})"

    def clean(self):
        super().clean()
        if not self.client_id:
            return

        # Validate the client has an address of type delivery
        if not self.client.has_delivery_address():
            raise ValidationError({
                'client': f"El cliente '{self.client.name}' no tiene una dirección de envío válida. Por favor, agregue una dirección de tipo 'Ubicacion Fisica' para este cliente."
            })
        

    def mark_completed(self):
        """Mark this route client order as completed"""
        from django.utils import timezone
        self.is_completed = True
        self.completed_at = timezone.now()
        self.save()

class RouteClient(TimeStampedModel):
    """Regular client assignment to a route (for recurring weekly visits)"""
    route = models.ForeignKey(Route, related_name='route_clients', on_delete=models.CASCADE)
    client = models.ForeignKey('clients.Client', verbose_name="Cliente", related_name='client_routes', on_delete=models.CASCADE)
    sequence = models.PositiveIntegerField(help_text="Default sequence order for this client", verbose_name="Ordinal")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    notes = models.TextField(blank=True, null=True, verbose_name="Notas")
    interval_weeks = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(4)],
        verbose_name='Intervalo (semanas)',
        help_text='Frecuencia de visita expresada en semanas (1 a 4).',
    )
    anchor_date = models.DateField(
        default=date.today,
        verbose_name='Fecha de inicio de ciclo',
        help_text='Fecha base para calcular cada cuántas semanas corresponde la visita.',
    )

    objects = RouteClientManager()
    
    class Meta:
        unique_together = ('route', 'client')
        ordering = ['sequence']
        indexes = [
            models.Index(fields=['is_active'], name='routes_client_active_idx'),
            models.Index(fields=['interval_weeks'], name='routes_client_interval_idx'),
        ]

    def __str__(self):
        return f"{self.client} in {self.route.name} (sequence: {self.sequence})"

    def _align_anchor_date_to_route_weekday(self):
        if not self.route_id or not self.anchor_date:
            return

        route_weekday_index = WEEKDAY_TO_INDEX.get(self.route.weekday)
        if route_weekday_index is None:
            return

        weekday_delta = (self.anchor_date.weekday() - route_weekday_index) % 7
        self.anchor_date = self.anchor_date - timedelta(days=weekday_delta)

    def is_due_on(self, target_date: date) -> bool:
        if not self.route_id or not self.is_active:
            return False

        if self.route.weekday != target_date.strftime('%A').lower():
            return False

        if target_date < self.anchor_date:
            return False

        weeks_since_anchor = (target_date - self.anchor_date).days // 7
        return weeks_since_anchor % self.interval_weeks == 0

    def _validate_client_delivery_address(self):
        if not self.client_id:
            return

        if not self.client.has_delivery_address():
            raise ValidationError({
                'client': f"El cliente '{self.client.name}' no tiene una dirección de envío válida. Por favor, agregue una dirección de tipo 'Ubicacion Fisica' para este cliente."
            })
    
    def clean(self):
        super().clean()
        self._validate_client_delivery_address()

    def save(self, *args, **kwargs):
        self._align_anchor_date_to_route_weekday()
        self._validate_client_delivery_address()
        return super().save(*args, **kwargs)
