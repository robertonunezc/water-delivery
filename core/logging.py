from .middleware.request_id import get_request_id


class RequestIdFilter:
    def filter(self, record):
        record.request_id = get_request_id() or "-"
        return True