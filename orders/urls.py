from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('update/<int:order_pk>', views.update_order, name='order_update'),
    path('<int:client_pk>/', views.create_order, name='create_order'),
]
