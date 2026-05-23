"""
URL configuration for water_delivery project.

The `urlpatterns` list routes URLs to view. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView

from orders import views as order_views
from routes import views as route_views
from invoice import views as invoice_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('administrador/pedidos/', order_views.list_orders_dashboard, name='admin_orders'),
    path('administrador/rutas/', route_views.list_admin, name='admin_routes'),
    path('administrador/rutas/crear/', route_views.create_admin, name='admin_create_route'),
    path('administrador/rutas/<int:pk>/editar/', route_views.update_admin, name='admin_update_route'),
    path('administrador/facturas/', invoice_views.list_invoices_admin, name='admin_invoices'),
    path('administrador/facturas/crear/', invoice_views.create_invoice_admin, name='admin_create_invoice'),
    path('administrador/facturas/<int:pk>/editar/', invoice_views.edit_invoice_admin, name='admin_edit_invoice'),
    path('administrador/facturas/<int:pk>/eliminar-pedido/<int:link_pk>/', invoice_views.remove_order_link_admin, name='admin_remove_invoice_order_link'),
    path(
        'admin/invoice/invoiceschedule/add/',
        RedirectView.as_view(pattern_name='admin:billing_invoiceschedule_add', permanent=False, query_string=True),
    ),
    path('', include('invoice.urls')),
    path('clients/', include('clients.urls')),
    # path('products/', include('product.urls')),
    path('payments/', include('payment.urls')),
    path('reports/', include('report.urls')),
    path('routes/', include('routes.urls')),
    path('orders/', include('orders.urls')),
    path('notifications/', include('notification.urls')),
    path('', include('core.urls')),
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
