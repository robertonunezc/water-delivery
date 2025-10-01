from django.contrib import admin
from .models import Route, RouteClient, RouteClientOrder

class RouteClientInline(admin.TabularInline):
    model = RouteClient
    extra = 1
    fields = ('client', 'sequence', 'frequency', 'is_active', 'notes')
    ordering = ('sequence',)
    verbose_name = "Cliente de la Ruta"
    verbose_name_plural = "Clientes de la Ruta"

class RouteClientOrderInline(admin.TabularInline):
    model = RouteClientOrder
    extra = 0
    fields = ('client', 'order', 'sequence', 'visit_date', 'is_completed', 'notes')
    readonly_fields = ('completed_at',)
    ordering = ('sequence',)

@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('name', 'transportation', 'weekday', 'is_active', 'client_count', 'created_at')
    list_filter = ('weekday', 'is_active', 'transportation', 'created_at')
    search_fields = ('name', 'description', 'transportation__license_plate')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [RouteClientInline,]
    
    def client_count(self, obj):
        return obj.route_clients.filter(is_active=True).count()
    client_count.short_description = 'Active Clients'


class RouteClientAdmin(admin.ModelAdmin):
    list_display = ('client', 'route', 'sequence', 'frequency', 'is_active')
    list_filter = ('frequency', 'is_active', 'route__weekday', 'route__transportation')
    search_fields = ('client__name', 'route__name', 'route__transportation__license_plate')
    ordering = ('route', 'sequence')
    
    class Meta:
        verbose_name = 'Route Client Assignment'
        verbose_name_plural = 'Route Client Assignments'


class RouteClientOrderAdmin(admin.ModelAdmin):
    list_display = ('client', 'route', 'order', 'visit_date', 'sequence', 'is_completed')
    list_filter = ('is_completed', 'visit_date', 'route__weekday', 'route__transportation')
    search_fields = ('client__name', 'route__name', 'order__id')
    ordering = ('visit_date', 'route', 'sequence')
    readonly_fields = ('completed_at',)
    date_hierarchy = 'visit_date'
    
    class Meta:
        verbose_name = 'Route Client Order'
        verbose_name_plural = 'Route Client Orders'
