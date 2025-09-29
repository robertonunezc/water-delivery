from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import ClientTenant, Domain

@admin.register(ClientTenant)
class ClientTenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'paid_until', 'on_trial', 'created_on')
    search_fields = ('name',)