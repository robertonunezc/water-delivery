from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('', views.list_orders, name='list'),
    path('<int:order_pk>/update/', views.update_order, name='update_order'),
    path('<int:order_pk>/cancel/', views.cancel_order, name='cancel_order'),
    path('create/<int:client_pk>/', views.create_order, name='create_order'),
    path('<int:order_id>/split/', views.split_order, name='split_order'),
    path('<int:client_pk>/history/', views.client_order_history, name='client_order_history'),
]
