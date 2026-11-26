from django.urls import path
from . import views

app_name = 'payment'

urlpatterns = [
    path('', views.payment_list_view, name='list_payments'),
    path('create/', views.create_payment, name='create_payment'),
    path('order/<int:order_id>/', views.order_payments_view, name='order_payments'),
    path('<int:payment_id>/reverse/', views.reverse_payment_view, name='reverse_payment_preview'),
    path(
        'deposits/<int:transaction_id>/reverse/',
        views.reverse_deposit_view,
        name='reverse_deposit_preview',
    ),
]
