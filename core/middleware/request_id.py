import uuid
import contextvars

# Context variable survives across async calls (safe for Django)
_request_id_ctx_var = contextvars.ContextVar("request_id", default=None)


def get_request_id():
    return _request_id_ctx_var.get()


class RequestIdMiddleware:
    HEADER_NAME = "HTTP_X_REQUEST_ID"
    RESPONSE_HEADER = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get(self.HEADER_NAME) or str(uuid.uuid4())

        token = _request_id_ctx_var.set(request_id)
        try:
            response = self.get_response(request)
            response[self.RESPONSE_HEADER] = request_id
            return response
        finally:
            _request_id_ctx_var.reset(token)