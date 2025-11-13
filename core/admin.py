from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Employee, Transport

class UserAdmin(BaseUserAdmin):
    # Do not inline Employee here. We want Employee created/managed only from the Employee admin.
    pass

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('user', 'position', 'phone', 'city', 'state', 'contract_type')
    list_filter = ('position', 'contract_type', 'city', 'state')
    search_fields = ('user__first_name', 'user__last_name', 'user__email', 'curp', 'rfc', 'phone')
    # Allow assigning or creating a user from the Employee admin.
    verbose_name = "Empleado"
    verbose_name_plural = "Empleados"
    fieldsets = (
       
        ('Informacion personal', {
            'fields': ('nombre', 'apellidos', 'sexo', 'curp', 'rfc', 'phone')
        }),
        ('Dirección', {
            'fields': ('street_number', 'city', 'state', 'zip_code')
        }),
        ('Empleo', {
            'fields': ('position', 'contract_type')
        }),
         ('Usuario acceso al sistema', {
            'fields': ('user',)
        }),
    )
    def save_model(self, request, obj, form, change):
        """
        If an Employee is saved without a linked User, create a new User with an unusable password
        and assign it to the employee. This allows creating employees that also get a User account
        from the admin UI.
        """
        # If no user is set, save the employee first so we have a PK to build a username
        if obj.user is None:
            super().save_model(request, obj, form, change)
            from django.contrib.auth.models import User as AuthUser

            base_username = f"employee_{obj.pk}"
            username = base_username
            i = 1
            while AuthUser.objects.filter(username=username).exists():
                username = f"{base_username}_{i}"
                i += 1

            user = AuthUser.objects.create(username=username)
            user.set_unusable_password()
            user.save()

            obj.user = user
            obj.save()
        else:
            super().save_model(request, obj, form, change)

@admin.register(Transport)
class TransportAdmin(admin.ModelAdmin):
    list_display = ('license_plate', 'model', 'capacity_liters', 'assigned_driver', 'is_active')
    list_filter = ('is_active', 'model', 'assigned_driver__position')
    search_fields = ('license_plate', 'model', 'assigned_driver__user__first_name', 'assigned_driver__user__last_name')
    ordering = ('license_plate',)
    
    fieldsets = (
        ('Información del Vehículo', {
            'fields': ('license_plate', 'model', 'capacity_liters')
        }),
        ('Asignación', {
            'fields': ('assigned_driver', 'is_active')
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('assigned_driver__user')

# Unregister the original User admin and register our (inline-free) UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
