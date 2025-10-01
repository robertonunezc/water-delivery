from django.db import models
from datetime import date

# Create your models here.
WEEKDAY_CHOICES = [
    ('monday', 'Lunes'),
    ('tuesday', 'Martes'),
    ('wednesday', 'Miércoles'),
    ('thursday', 'Jueves'),
    ('friday', 'Viernes'),
    ('saturday', 'Sábado'),
    ('sunday', 'Domingo'),
]

class Route(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nombre de la Ruta")
    description = models.TextField(blank=True, null=True, verbose_name="Descripción")
    transportation = models.ForeignKey('core.Transport', related_name='routes', on_delete=models.SET_NULL, null=True, verbose_name="Vehículo")
    weekday = models.CharField(max_length=10, choices=WEEKDAY_CHOICES, default='monday', verbose_name="Día de la Semana")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Fecha de Actualización")

    class Meta:
        verbose_name = 'Ruta'
        verbose_name_plural = 'Rutas'
        unique_together = ('transportation', 'weekday')
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

class RouteClientOrder(models.Model):
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

    def mark_completed(self):
        """Mark this route client order as completed"""
        from django.utils import timezone
        self.is_completed = True
        self.completed_at = timezone.now()
        self.save()

class RouteClient(models.Model):
    """Regular client assignment to a route (for recurring weekly visits)"""
    route = models.ForeignKey(Route, related_name='route_clients', on_delete=models.CASCADE)
    client = models.ForeignKey('clients.Client', verbose_name="Cliente", related_name='client_routes', on_delete=models.CASCADE)
    sequence = models.PositiveIntegerField(help_text="Default sequence order for this client", verbose_name="Ordinal")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    notes = models.TextField(blank=True, null=True, verbose_name="Notas")
    frequency = models.CharField(max_length=50, choices=[
        ('weekly', 'Semanal'),
        ('biweekly', 'Quincenal'),
        ('monthly', 'Mensual'),
    ], default='weekly')
    
    class Meta:
        unique_together = ('route', 'client')
        ordering = ['sequence']
        indexes = [
            models.Index(fields=['is_active'], name='routes_client_active_idx'),
            models.Index(fields=['frequency'], name='routes_client_frequency_idx'),
        ]

    def __str__(self):
        return f"{self.client} in {self.route.name} (sequence: {self.sequence})"