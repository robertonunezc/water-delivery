from django.urls import path
from . import views

app_name = 'routes'

urlpatterns = [
    path('', views.employee_routes_list, name='list'),
    path('my-routes/', views.employee_routes_list, name='employee_routes'),
    path('<int:route_id>/', views.route_detail, name='detail'),
    path('<int:route_id>/clients.json', views.route_clients_json, name='clients_json'),
]
