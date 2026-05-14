from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from tenant_client.public_admin import public_admin
from core.views import health_check

urlpatterns = [
    path('admin/', public_admin.urls),  # Public-only admin: tenant + domain management
    path('health/', health_check, name='health_check'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
