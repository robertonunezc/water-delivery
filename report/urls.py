from django.urls import path
from . import views

app_name = 'report'

urlpatterns = [
    path('credit/', views.credit_report, name='credit_report'),
    path('credit/csv/', views.credit_report_csv, name='credit_report_csv'),
    path('credit/client/<int:client_id>/', views.client_credit_report, name='client_credit_report'),
    path('client-debt/', views.client_debt_report, name='client_debt'),
    path('breakdown-payment-method/', views.breakdown_payment_method, name='breakdown_payment_method'),
    path('breakdown-payment-method/csv/', views.breakdown_payment_method_csv, name='breakdown_payment_method_csv'),
    path('orders/', views.orders_report, name='orders_report'),
    path('orders/csv/', views.orders_report_csv, name='orders_report_csv'),
    path('pending-payments/', views.pending_payments_report, name='pending_payments'),
]
