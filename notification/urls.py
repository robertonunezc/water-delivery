from django.urls import path
from notification import views

app_name = 'notification'

urlpatterns = [
    path('send/<int:notification_id>', views.send_notification_view, name='send_notification'),
]