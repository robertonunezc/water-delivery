from django.contrib.auth.decorators import login_required

from django.urls import path
import views 
app_name = 'billing'

urlpatterns = [
    # Define billing-related URL patterns here
    path('orders/<int:client_pk>/billable-orders/', views.billable_orders, name='billable_orders'),
    path('admin/billing/invoiceorderlink/billing-record/<int:billingRecordId>/client/', views.billable_orders, name='invoiceorderlink_client'),
]
