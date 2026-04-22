"""
URL configuration for water_delivery project.

The `urlpatterns` list routes URLs to views. For more information please see:
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
from django.views.generic.base import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
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
