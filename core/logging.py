from .middleware.request_id import get_request_id
from .middleware.log_context import get_tenant, get_user


class LogContextFilter:
    def filter(self, record):
        record.request_id = get_request_id() or "-"
        record.tenant = get_tenant() or "-"
        record.user = get_user() or "-"
        return True