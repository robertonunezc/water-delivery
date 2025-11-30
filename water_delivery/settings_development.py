from .settings import *

# Development overrides
DEBUG = True

# Use a local secret for development (keep default from base settings or env)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', SECRET_KEY)

# Allow localhost by default
ALLOWED_HOSTS = ['localhost', '127.0.0.1']
import os
from dotenv import load_dotenv
load_dotenv('.env')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'water_delivery'),
        'USER': os.environ.get('POSTGRES_USER', 'user'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'password'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}