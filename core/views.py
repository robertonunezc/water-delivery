import logging
import os

import redis
from django.http import JsonResponse
from django.shortcuts import render


logger = logging.getLogger(__name__)

def home(request):
    """Home page view - shows dashboard for authenticated users, welcome page for anonymous users"""
    context = {
        'is_authenticated': request.user.is_authenticated,
        'user': request.user if request.user.is_authenticated else None,
    }
    return render(request, 'home.html', context)

def health_check(request):
    """Health check endpoint for monitoring"""
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as e:
        logger.exception("Health check failed on database")
        return JsonResponse(
            {'status': 'error', 'dependency': 'database', 'message': str(e)},
            status=500,
        )

    redis_host = os.environ.get('REDIS_HOST', 'localhost')
    redis_port = int(os.environ.get('REDIS_PORT', '6379'))
    redis_password = os.environ.get('REDIS_PASSWORD') or None

    try:
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            db=0,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        r.ping()
    except Exception as e:
        logger.exception("Health check failed on redis")
        return JsonResponse(
            {'status': 'error', 'dependency': 'redis', 'message': str(e)},
            status=500,
        )

    return JsonResponse({'status': 'ok'})