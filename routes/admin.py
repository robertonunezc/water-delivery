from django.contrib import admin
from .models import Route, RouteEmployee, RouteClient


class RouteEmployeeInline(admin.TabularInline):
    model = RouteEmployee
    extra = 1
    fields = ('employee', 'status', 'assigned_at')
    readonly_fields = ('assigned_at',)


class RouteClientInline(admin.TabularInline):
    model = RouteClient
    extra = 1
    fields = ('client', 'sequence', 'day_to_visit', 'frecuency', 'note')
    ordering = ('sequence',)


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'employee_count', 'client_count', 'created_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [RouteEmployeeInline, RouteClientInline]
    
    def employee_count(self, obj):
        return obj.route_employees.filter(status='active').count()
    employee_count.short_description = 'Active Employees'
    
    def client_count(self, obj):
        return obj.route_clients.count()
    client_count.short_description = 'Clients'


@admin.register(RouteEmployee)
class RouteEmployeeAdmin(admin.ModelAdmin):
    list_display = ('employee', 'route', 'status', 'assigned_at')
    list_filter = ('status', 'assigned_at', 'route')
    search_fields = ('employee__user__first_name', 'employee__user__last_name', 'route__name')
    readonly_fields = ('assigned_at',)


@admin.register(RouteClient)
class RouteClientAdmin(admin.ModelAdmin):
    list_display = ('client', 'route', 'sequence', 'day_to_visit', 'frecuency')
    list_filter = ('day_to_visit', 'frecuency', 'route')
    search_fields = ('client__name', 'route__name')
    ordering = ('route', 'sequence')
    
    class Meta:
        verbose_name = 'Route Client Assignment'
        verbose_name_plural = 'Route Client Assignments'
