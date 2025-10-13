from django.urls import path
from . import views

app_name = 'report'

urlpatterns = [
    path('client-debt/', views.client_debt_report, name='client_debt'),
    path('clients-full/', views.clients_full_report, name='client_full'),
    path('orders/', views.orders_report, name='orders_report'),
]