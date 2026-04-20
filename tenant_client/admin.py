from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import ClientTenant, Domain
@admin.register(ClientTenant)
class ClientTenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'schema_name', 'paid_until', 'on_trial', 'created_on')
    search_fields = ('name', 'schema_name')
    list_filter = ('on_trial',)


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'tenant', 'is_primary')
    search_fields = ('domain', 'tenant__name')
    list_filter = ('is_primary',)
    raw_id_fields = ('tenant',)