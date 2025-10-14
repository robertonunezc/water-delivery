from django.urls import path
from . import views

app_name = 'report'

urlpatterns = [
    path('client-debt/', views.client_debt_report, name='client_debt'),
    path('today/', views.today, name='today_report'),
    path('orders/', views.orders_report, name='orders_report'),
]