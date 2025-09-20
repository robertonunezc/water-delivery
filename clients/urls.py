from django.urls import path
from . import views

app_name = 'clients'

urlpatterns = [
    path('', views.list, name='list'),
    # path('create/', views.create, name='create'),
    # path('<int:pk>/', views.detail, name='detail'),
    # path('<int:pk>/update/', views.update, name='update'),
    # path('<int:pk>/delete/', views.delete, name='delete'),
]