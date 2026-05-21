from django.urls import path
from . import views

app_name = 'clients'

urlpatterns = [
    path('', views.list, name='list'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/editar/', views.edit_v2, name='edit_v2'),
    path('<int:pk>/update/', views.update_client, name='update'),
    path('<int:pk>/pay-credit/', views.pay_credit, name='pay_credit'),
    path('<int:client_pk>/orders/', views.client_orders, name='client_orders'),
    path('crear-v2/', views.create_v2, name='create_v2'),
    path('crear/', views.create_v2, name='create'),
    # path('<int:pk>/delete/', views.delete, name='delete'),
]