from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from core import views


class DashboardDateRangeTests(SimpleTestCase):
    def test_yesterday_preset_uses_previous_day(self) -> None:
        from core.services.dashboard_service import get_dashboard_date_range

        selected_range = get_dashboard_date_range("yesterday", today=date(2026, 7, 1))

        self.assertEqual(selected_range.start_date, date(2026, 6, 30))
        self.assertEqual(selected_range.end_date, date(2026, 6, 30))
        self.assertEqual(selected_range.label, "Ayer")

    def test_last_week_preset_uses_previous_monday_to_sunday(self) -> None:
        from core.services.dashboard_service import get_dashboard_date_range

        selected_range = get_dashboard_date_range("last_week", today=date(2026, 7, 1))

        self.assertEqual(selected_range.start_date, date(2026, 6, 22))
        self.assertEqual(selected_range.end_date, date(2026, 6, 28))
        self.assertEqual(selected_range.label, "Semana pasada")

    def test_last_month_preset_uses_previous_calendar_month(self) -> None:
        from core.services.dashboard_service import get_dashboard_date_range

        selected_range = get_dashboard_date_range("last_month", today=date(2026, 1, 15))

        self.assertEqual(selected_range.start_date, date(2025, 12, 1))
        self.assertEqual(selected_range.end_date, date(2025, 12, 31))
        self.assertEqual(selected_range.label, "Mes pasado")

    def test_custom_preset_uses_valid_custom_dates(self) -> None:
        from core.services.dashboard_service import get_dashboard_date_range

        selected_range = get_dashboard_date_range(
            "custom",
            custom_start="2026-06-05",
            custom_end="2026-06-12",
            today=date(2026, 7, 1),
        )

        self.assertEqual(selected_range.start_date, date(2026, 6, 5))
        self.assertEqual(selected_range.end_date, date(2026, 6, 12))
        self.assertEqual(selected_range.label, "Personalizado")


class HealthCheckViewTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def _request(self, path: str = "/health/ready/"):
        request = self.factory.get(path, HTTP_HOST="testserver")
        request.tenant = SimpleNamespace(schema_name="tenant1")
        return request

    def test_live_health_check_returns_ok(self) -> None:
        response = views.health_live(self._request("/health/live/"))

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, {"status": "ok", "check": "live"})

    @patch("core.views._check_redis", return_value={"redis": "ok"})
    @patch("core.views._check_database", return_value={"database": "ok", "schema_name": "tenant1"})
    def test_ready_health_check_returns_ok_when_dependencies_pass(
        self,
        _database_check,
        _redis_check,
    ) -> None:
        response = views.health_ready(self._request())

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["check"], "ready")
        self.assertEqual(payload["tenant"]["schema_name"], "tenant1")
        self.assertEqual(
            payload["dependencies"],
            {"database": "ok", "schema_name": "tenant1", "redis": "ok"},
        )

    @patch("core.views._check_redis", return_value={"redis": "ok"})
    @patch("core.views._check_database", return_value={"database": "ok", "schema_name": "public"})
    @patch("core.views.logger")
    def test_ready_health_check_fails_when_tenant_schema_mismatches(
        self,
        logger,
        _database_check,
        _redis_check,
    ) -> None:
        response = views.health_ready(self._request())

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["dependency"], "tenant")
        logger.error.assert_called_once()
