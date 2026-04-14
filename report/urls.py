from django.urls import path
from . import views

app_name = 'report'

urlpatterns = [
    path('client-debt/', views.client_debt_report, name='client_debt'),
    path('breakdown-payment-method/', views.breakdown_payment_method, name='breakdown_payment_method'),
    path('today/csv/', views.today_csv, name='today_csv'),
    path('orders/', views.orders_report, name='orders_report'),
]