"""
URL configuration for public schema (main domain).

This URLconf handles routes for the public tenant, which manages
multi-tenant administration and tenant provisioning.

Routes available at: https://yourdomain.com/
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),  # Django admin interface
    path('admin/tenant-management/', include('tenant_client.urls')),  # Superuser-only tenant management
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
