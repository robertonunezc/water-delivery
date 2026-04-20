from django_tenants.admin import TenantAdminMixin
from unfold.admin import ModelAdmin
from .models import ClientTenant, Domain
from .public_admin import public_admin


class ClientTenantAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ('name', 'schema_name', 'paid_until', 'on_trial', 'created_on')
    search_fields = ('name', 'schema_name')
    list_filter = ('on_trial',)


class DomainAdmin(ModelAdmin):
    list_display = ('domain', 'tenant', 'is_primary')
    search_fields = ('domain', 'tenant__name')
    list_filter = ('is_primary',)
    raw_id_fields = ('tenant',)


# Register ONLY on the public admin site — invisible to tenant schemas
public_admin.register(ClientTenant, ClientTenantAdmin)
public_admin.register(Domain, DomainAdmin)