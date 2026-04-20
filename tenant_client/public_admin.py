from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin


class PublicAdminSite(AdminSite):
    """Admin site served only on the public schema (root domain).
    Handles tenant and domain management. Not accessible from tenant subdomains."""
    site_header = "PuriGest — Gestión de Tenants"
    site_title = "PuriGest Public Admin"
    index_title = "Administración de Tenants"


public_admin = PublicAdminSite(name="public_admin")

# Register User so superadmins can be managed from the public admin
public_admin.register(get_user_model(), UserAdmin)
