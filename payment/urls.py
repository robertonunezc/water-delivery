from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    path('create/', views.create_payment, name='create_payment'),
]