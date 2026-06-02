"""
URL configuration for tenant schemas (subdomains).

This URLconf handles routes for individual tenant schemas,
providing access to business operations (clients, orders, billing, etc.).

Routes available at: https://tenant1.yourdomain.com/, https://tenant2.yourdomain.com/, etc.
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from orders import views as order_views
from clients import views as client_views
from routes import views as route_views
from invoice import views as invoice_views
urlpatterns = [
    path('admin/', admin.site.urls),  # Tenant-specific admin
    path('administrador/pedidos/', order_views.list_orders_admin, name='admin_orders'),
    path('administrador/clientes/', client_views.list_admin, name='admin_clients'),
    path('administrador/clientes/crear/', client_views.create_v2, name='admin_create_client'),
    path('administrador/clientes/<int:pk>/editar/', client_views.edit_v2, name='admin_edit_client'),

    path('administrador/rutas/', route_views.list_admin, name='admin_routes'),
    path('administrador/rutas/crear/', route_views.create_admin, name='admin_create_route'),
    path('administrador/rutas/<int:pk>/editar/', route_views.update_admin, name='admin_update_route'),
    path('administrador/facturas/', invoice_views.list_invoices_admin, name='admin_invoices'),
    path('administrador/facturas/crear/', invoice_views.create_invoice_admin, name='admin_create_invoice'),
    path('administrador/facturas/<int:pk>/editar/', invoice_views.edit_invoice_admin, name='admin_edit_invoice'),
    path('administrador/facturas/<int:pk>/eliminar-pedido/<int:link_pk>/', invoice_views.remove_order_link_admin, name='admin_remove_invoice_order_link'),

    path('clients/', include('clients.urls')),
    path('orders/', include('orders.urls')),
    path('billing/', include('invoice.urls')),
    path('payments/', include('payment.urls')),
    path('routes/', include('routes.urls')),
    path('notifications/', include('notification.urls')),
    path('reports/', include('report.urls')),
    path('', include('core.urls')),
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
