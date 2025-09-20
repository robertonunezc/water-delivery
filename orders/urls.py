from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('client/<int:client_pk>/new/', views.new_order, name='client_new'),
    # detail view should exist elsewhere; using new_order as placeholder for now
    path('<int:pk>/', views.new_order, name='detail'),
]
