import contextvars

_tenant_ctx_var = contextvars.ContextVar("tenant", default=None)
_user_ctx_var = contextvars.ContextVar("user", default=None)

def get_tenant():
    return _tenant_ctx_var.get()

def get_user():
    return _user_ctx_var.get()

class LogContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_name = getattr(request.tenant, 'schema_name', None) if hasattr(request, 'tenant') else None
        
        user = getattr(request, 'user', None)
        user_display = None
        if user and user.is_authenticated:
            user_display = getattr(user, 'email', None) or getattr(user, 'username', None) or str(user.pk)

        token_tenant = _tenant_ctx_var.set(tenant_name)
        token_user = _user_ctx_var.set(user_display)

        try:
            return self.get_response(request)
        finally:
            _tenant_ctx_var.reset(token_tenant)
            _user_ctx_var.reset(token_user)
