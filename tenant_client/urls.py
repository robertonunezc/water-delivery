"""
URL configuration for tenant_client app.

Provides superuser-only endpoints for tenant management operations.
These URLs are designed to be included under the /admin/ path.
"""
from django.urls import path
from . import views

app_name = 'tenant_client'

urlpatterns = [
    path('', views.tenant_list, name='list'),
    path('create/', views.tenant_create, name='create'),
    path('api/<str:schema_name>/', views.tenant_detail_api, name='detail_api'),
]
