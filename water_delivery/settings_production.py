import os
from .settings import *

# Production overrides
DEBUG = False

# Ensure the secret is provided via env in production
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', SECRET_KEY)

# Example: tighten allowed hosts in production
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if os.environ.get('DJANGO_ALLOWED_HOSTS') else ['*']

# Database: the base settings use env vars already, so no change required here.

# Production static settings
STATIC_ROOT = '/app/staticfiles/'
STATIC_URL = '/static/'

# Media files
MEDIA_ROOT = '/app/media/'
MEDIA_URL = '/media/'

# settings_production.py (add/replace LOGGING)
from pythonjsonlogger import jsonlogger

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'fmt': '%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
from dotenv import load_dotenv
load_dotenv('.env.prod')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'water_delivery'),
        'USER': os.environ.get('POSTGRES_USER', 'user'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'password'),
        'HOST': os.environ.get('POSTGRES_HOST', 'host.docker.internal'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}
