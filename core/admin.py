from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Employee

class EmployeeInline(admin.StackedInline):
    model = Employee
    can_delete = False
    verbose_name_plural = "employee"

class UserAdmin(BaseUserAdmin):
    inlines = [EmployeeInline]

# Unregister the original User admin
admin.site.unregister(User)
# Register the User admin with Employee inline
admin.site.register(User, UserAdmin)
