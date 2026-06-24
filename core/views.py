import logging
import os

import redis
from django.http import JsonResponse
from django.shortcuts import render
from invoice import services as invoice_services
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def home(request):
    """Home page view - shows dashboard for authenticated users, welcome page for anonymous users"""
    current_week_first_day = date.today() - timedelta(days=date.today().weekday())
    current_week_last_day = current_week_first_day + timedelta(days=6)
    print(current_week_first_day, current_week_last_day)
    today_invoices = invoice_services.get_clients_needing_billing(
        start_date=current_week_first_day, 
        end_date=current_week_last_day
    )
    print(today_invoices)
    context = {
        'is_authenticated': request.user.is_authenticated,
        'user': request.user if request.user.is_authenticated else None,
        'today_invoices_count': len(today_invoices),
    }
    return render(request, 'home.html', context)

def _tenant_context(request) -> dict[str, str | None]:
    tenant = getattr(request, "tenant", None)
    schema_name = getattr(tenant, "schema_name", None)
    return {
        "schema_name": schema_name,
        "host": request.get_host(),
    }


def _check_database(request) -> dict[str, str]:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        schema_name = cursor.fetchone()[0]

    active_schema = getattr(connection, "schema_name", schema_name)
    return {
        "database": "ok",
        "schema_name": active_schema,
    }


def _check_redis() -> dict[str, str]:
    redis_host = os.environ.get('REDIS_HOST', 'localhost')
    redis_port = int(os.environ.get('REDIS_PORT', '6379'))
    redis_password = os.environ.get('REDIS_PASSWORD') or None

    client = redis.Redis(
        host=redis_host,
        port=redis_port,
        password=redis_password,
        db=0,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    client.ping()
    return {"redis": "ok"}


def health_live(request):
    """Process liveness endpoint for load balancers and uptime probes."""
    return JsonResponse({"status": "ok", "check": "live"})


def health_ready(request):
    """Readiness endpoint that validates tenant context, database, and Redis."""
    tenant = _tenant_context(request)

    try:
        dependencies = _check_database(request)
    except Exception as exc:
        logger.exception("Health readiness failed on database")
        return JsonResponse(
            {
                "status": "error",
                "check": "ready",
                "dependency": "database",
                "message": str(exc),
                "tenant": tenant,
            },
            status=500,
        )

    try:
        dependencies.update(_check_redis())
    except Exception as exc:
        logger.exception("Health readiness failed on redis")
        return JsonResponse(
            {
                "status": "error",
                "check": "ready",
                "dependency": "redis",
                "message": str(exc),
                "tenant": tenant,
                "dependencies": dependencies,
            },
            status=500,
        )

    if tenant["schema_name"] and dependencies["schema_name"] != tenant["schema_name"]:
        logger.error(
            "Health readiness failed on tenant schema validation",
            extra={
                "request_schema": tenant["schema_name"],
                "database_schema": dependencies["schema_name"],
            },
        )
        return JsonResponse(
            {
                "status": "error",
                "check": "ready",
                "dependency": "tenant",
                "message": "Resolved tenant schema does not match active database schema.",
                "tenant": tenant,
                "dependencies": dependencies,
            },
            status=500,
        )

    return JsonResponse(
        {
            "status": "ok",
            "check": "ready",
            "tenant": tenant,
            "dependencies": dependencies,
        }
    )


health_check = health_ready
