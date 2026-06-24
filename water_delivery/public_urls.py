from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from tenant_client.public_admin import public_admin
from core import views as core_views

urlpatterns = [
    path('admin/', public_admin.urls),  # Public-only admin: tenant + domain management
    path('health/', core_views.health_ready, name='health_check'),
    path('health/live', core_views.health_live, name='health_live'),
    path('health/live/', core_views.health_live),
    path('health/ready', core_views.health_ready, name='health_ready'),
    path('health/ready/', core_views.health_ready),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
