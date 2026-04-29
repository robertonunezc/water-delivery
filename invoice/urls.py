from django.urls import path
from . import views
app_name = 'invoice'

urlpatterns = [
    # Define billing-related URL patterns here
    path('orders/<int:client_pk>/invoiceable-orders/', views.invoiceable_orders, name='invoiceable_orders'),
    # Invoice-prefixed aliases for admin JS endpoints
    path(
        'admin/invoice/invoiceorderlink/invoiceable-orders/<int:client_pk>/',
        views.invoiceable_orders,
        name='invoiceorderlink_invoiceable_orders',
    ),
    path(
        'admin/invoice/invoiceorderlink/invoice/<int:invoice_id>/client/',
        views.invoice_client,
        name='invoiceorderlink_invoice_client',
    ),
]
