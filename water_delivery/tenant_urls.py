"""
URL configuration for tenant schemas (subdomains).

This URLconf handles routes for individual tenant schemas,
providing access to business operations (clients, orders, billing, etc.).

Routes available at: https://tenant1.yourdomain.com/, https://tenant2.yourdomain.com/, etc.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),  # Tenant-specific admin
    path('clients/', include('clients.urls')),
    path('orders/', include('orders.urls')),
    path('billing/', include('billing.urls')),
    path('payments/', include('payment.urls')),
    path('routes/', include('routes.urls')),
    path('notifications/', include('notification.urls')),
    path('reports/', include('report.urls')),
    path('', include('core.urls')),
]
