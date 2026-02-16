from django.contrib import admin
from django.contrib.admin import widgets
from django.forms import Media
from .models import Route, RouteClient, RouteClientOrder
from .forms import RouteClientForm, RouteClientInlineForm, RouteForm
from unfold.admin import ModelAdmin, StackedInline, TabularInline
class RouteClientInline(TabularInline):
    model = RouteClient
    form = RouteClientInlineForm
    extra = 1
    fields = ('client', 'sequence', 'frequency', 'is_active', 'notes', 'confirm_duplicate_assignment')
    ordering = ('sequence',)
    verbose_name = "Cliente de la Ruta"
    verbose_name_plural = "Clientes de la Ruta"
    
    class Media:
        js = ('routes/js/route_validation_fallback.js', 'routes/js/route_client_admin.js')
        css = {
            'all': ('routes/css/route_admin.css', 'admin/css/widgets.css')
        }
    
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.request = request
        return form

class RouteClientOrderInline(admin.TabularInline):
    model = RouteClientOrder
    extra = 0
    fields = ('client', 'order', 'sequence', 'visit_date', 'is_completed', 'notes')
    readonly_fields = ('completed_at',)
    ordering = ('sequence',)

@admin.register(Route)
class RouteAdmin(ModelAdmin):
    form = RouteForm
    list_display = ('name', 'transportation', 'weekday', 'is_active', 'client_count', 'created_at')
    list_filter = ('weekday', 'is_active', 'transportation', 'created_at')
    search_fields = ('name', 'description', 'transportation__license_plate')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [RouteClientInline,]
    
    class Media:
        js = ('routes/js/route_validation_fallback.js', 'routes/js/route_client_admin.js')
        css = {
            'all': ('routes/css/route_admin.css', 'admin/css/widgets.css')
        }
    
    def client_count(self, obj):
        return obj.route_clients.filter(is_active=True).count()
    client_count.short_description = 'Active Clients'
    
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.request = request
        return form


@admin.register(RouteClient)
class RouteClientAdmin(ModelAdmin):
    form = RouteClientForm
    list_display = ('client', 'route', 'sequence', 'frequency', 'is_active')
    list_filter = ('frequency', 'is_active', 'route__weekday', 'route__transportation')
    search_fields = ('client__name', 'route__name', 'route__transportation__license_plate')
    ordering = ('route', 'sequence')
    
    class Media:
        js = ('routes/js/route_validation_fallback.js', 'routes/js/route_client_admin.js')
        css = {
            'all': ('routes/css/route_admin.css', 'admin/css/widgets.css')
        }
    
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.request = request
        return form
    
    class Meta:
        verbose_name = 'Route Client Assignment'
        verbose_name_plural = 'Route Client Assignments'


@admin.register(RouteClientOrder)
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
