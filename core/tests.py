from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, RequestFactory, SimpleTestCase
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.utils import timezone
from django_celery_beat.schedulers import DatabaseScheduler
from django_celery_beat.schedulers import now as beat_now

User = get_user_model()

from .models import Employee
from .admin import EmployeeAdmin
from . import views


class HealthCheckViewTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def test_live_returns_ok_without_dependency_checks(self) -> None:
        request = self.factory.get("/health/live")

        with patch("core.views._check_database", side_effect=AssertionError("db check should not run")), patch(
            "core.views._check_redis", side_effect=AssertionError("redis check should not run")
        ):
            response = views.health_live(request)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok", "check": "live"})

    @patch("core.views._check_database", return_value={"database": "ok", "schema_name": "tenant_a"})
    @patch("core.views._check_redis", return_value={"redis": "ok"})
    def test_ready_returns_dependency_and_tenant_context(self, redis_check, database_check) -> None:
        request = self.factory.get("/health/ready", HTTP_HOST="tenant-a.example.com")
        request.tenant = type("Tenant", (), {"schema_name": "tenant_a"})()

        response = views.health_ready(request)

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "status": "ok",
                "check": "ready",
                "tenant": {
                    "schema_name": "tenant_a",
                    "host": "tenant-a.example.com",
                },
                "dependencies": {
                    "database": "ok",
                    "schema_name": "tenant_a",
                    "redis": "ok",
                },
            },
        )
        database_check.assert_called_once_with(request)
        redis_check.assert_called_once_with()

    @patch("core.views._check_redis", return_value={"redis": "ok"})
    @patch("core.views._check_database", return_value={"database": "ok", "schema_name": "public"})
    def test_ready_fails_when_request_tenant_and_db_schema_do_not_match(self, database_check, redis_check) -> None:
        request = self.factory.get("/health/ready", HTTP_HOST="tenant-a.example.com")
        request.tenant = type("Tenant", (), {"schema_name": "tenant_a"})()

        response = views.health_ready(request)

        self.assertEqual(response.status_code, 500)
        self.assertJSONEqual(
            response.content,
            {
                "status": "error",
                "check": "ready",
                "dependency": "tenant",
                "message": "Resolved tenant schema does not match active database schema.",
                "tenant": {
                    "schema_name": "tenant_a",
                    "host": "tenant-a.example.com",
                },
                "dependencies": {
                    "database": "ok",
                    "schema_name": "public",
                    "redis": "ok",
                },
            },
        )
        database_check.assert_called_once_with(request)
        redis_check.assert_called_once_with()


class TimezoneConfigurationTests(SimpleTestCase):
    def test_celery_beat_uses_aware_mexico_time(self) -> None:
        self.assertEqual(settings.TIME_ZONE, "America/Mexico_City")
        self.assertTrue(settings.USE_TZ)

        current_time = beat_now()

        self.assertTrue(timezone.is_aware(current_time))
        self.assertEqual(timezone.localtime(current_time).tzinfo.key, settings.TIME_ZONE)

    def test_database_scheduler_handles_crontab_hours(self) -> None:
        excluded_hours = DatabaseScheduler.get_excluded_hours_for_crontab_tasks()

        self.assertGreater(len(excluded_hours), 0)
