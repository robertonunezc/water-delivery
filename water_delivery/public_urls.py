"""
URL configuration for public schema (main domain).

This URLconf handles routes for the public tenant, which manages
multi-tenant administration and tenant provisioning.

Routes available at: https://yourdomain.com/
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),  # Django admin interface
    path('admin/tenant-management/', include('tenant_client.urls')),  # Superuser-only tenant management
]
