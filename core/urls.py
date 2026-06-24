from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('health/', views.health_ready, name='health_check'),
    path('health/live/', views.health_live, name='health_live'),
    path('health/ready/', views.health_ready, name='health_ready'),
]
