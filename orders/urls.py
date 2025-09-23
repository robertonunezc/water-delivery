from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('<int:order_pk>/update/', views.update_order, name='update_order'),
    path('<int:client_pk>/', views.create_order, name='create_order'),
]
