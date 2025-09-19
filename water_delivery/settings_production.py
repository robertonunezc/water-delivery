from .settings import *

# Production overrides
DEBUG = False

# Ensure the secret is provided via env in production
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', SECRET_KEY)

# Example: tighten allowed hosts in production
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if os.environ.get('DJANGO_ALLOWED_HOSTS') else ['your-production-domain.com']

# Database: the base settings use env vars already, so no change required here.

# Production static settings (example using S3 or collectstatic)
# STATIC_URL = 'https://your-cdn.example.com/static/'
