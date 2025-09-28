from django.shortcuts import render

def home(request):
    """Home page view - shows dashboard for authenticated users, welcome page for anonymous users"""
    context = {
        'is_authenticated': request.user.is_authenticated,
        'user': request.user if request.user.is_authenticated else None,
    }
    return render(request, 'home.html', context)