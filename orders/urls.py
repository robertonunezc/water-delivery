from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('', views.list_orders, name='list'),
    path('<int:order_pk>/update/', views.update_order, name='update_order'),
    path('create/<int:client_pk>/', views.create_order, name='create_order'),
]
