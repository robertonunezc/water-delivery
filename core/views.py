from django.http import JsonResponse
from django.shortcuts import render

def home(request):
    """Home page view - shows dashboard for authenticated users, welcome page for anonymous users"""
    context = {
        'is_authenticated': request.user.is_authenticated,
        'user': request.user if request.user.is_authenticated else None,
    }
    return render(request, 'home.html', context)

def health_check(request):
    """Health check endpoint for monitoring"""
    #Test database connection
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    # test redis connection
    import redis
    try:
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'ok'})