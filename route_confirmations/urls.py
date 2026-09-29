from django.urls import path

from . import views

app_name = 'route_confirmations'

urlpatterns = [
    path('administrador/confirmaciones/', views.list_confirmations, name='list'),
    path('administrador/confirmaciones/enviar/<int:route_client_id>/', views.send_confirmation, name='send'),
    path('administrador/confirmaciones/<int:pk>/ajustar/', views.override_confirmation_status, name='override'),
    path('confirmaciones/visita/<str:token>/<str:action>/', views.respond_to_confirmation, name='respond'),
]
