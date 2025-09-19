from .settings import *

# Development overrides
DEBUG = True

# Use a local secret for development (keep default from base settings or env)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', SECRET_KEY)

# Allow localhost by default
ALLOWED_HOSTS = ['localhost', '127.0.0.1']
