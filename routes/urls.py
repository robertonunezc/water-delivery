from django.urls import path
from . import views

app_name = 'routes'

urlpatterns = [
    path('', views.routes_by_transportation_and_day, name='list'),
    path('today/', views.today_route, name='today'),
    path('<int:route_id>/', views.route_detail, name='detail'),
    path('<int:route_id>/orders/', views.route_orders_by_date, name='orders_by_date'),
    path('order/<int:route_order_id>/complete/', views.mark_order_completed, name='mark_completed'),
    path('api/routes.json', views.routes_api_json, name='api_routes'),
]
