from django.urls import path

from . import views

app_name = "reminders"

urlpatterns = [
    path("", views.list, name="list"),
    path("nuevo/", views.create, name="create"),
    path("<int:pk>/editar/", views.edit, name="edit"),
    path("<int:pk>/listo/", views.complete, name="complete"),
    path("<int:pk>/eliminar/", views.delete, name="delete"),
]
