from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Employee, Transport

class EmployeeInline(admin.StackedInline):
    model = Employee
    can_delete = False
    verbose_name_plural = "employee"

class UserAdmin(BaseUserAdmin):
    inlines = [EmployeeInline]

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('user', 'position', 'phone', 'city', 'state', 'contract_type')
    list_filter = ('position', 'contract_type', 'city', 'state')
    search_fields = ('user__first_name', 'user__last_name', 'user__email', 'curp', 'rfc', 'phone')
    readonly_fields = ('user',)
    
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Personal Information', {
            'fields': ('curp', 'rfc', 'phone')
        }),
        ('Address', {
            'fields': ('street_number', 'city', 'state', 'zip_code')
        }),
        ('Employment', {
            'fields': ('position', 'contract_type')
        }),
    )

@admin.register(Transport)
class TransportAdmin(admin.ModelAdmin):
    list_display = ('license_plate', 'model', 'capacity_liters', 'assigned_driver', 'is_active')
    list_filter = ('is_active', 'model', 'assigned_driver__position')
    search_fields = ('license_plate', 'model', 'assigned_driver__user__first_name', 'assigned_driver__user__last_name')
    ordering = ('license_plate',)
    
    fieldsets = (
        ('Vehicle Information', {
            'fields': ('license_plate', 'model', 'capacity_liters')
        }),
        ('Assignment', {
            'fields': ('assigned_driver', 'is_active')
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('assigned_driver__user')

# Unregister the original User admin
admin.site.unregister(User)
# Register the User admin with Employee inline
admin.site.register(User, UserAdmin)
