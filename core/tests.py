import shutil
import subprocess
import textwrap
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone
from django_celery_beat.schedulers import DatabaseScheduler
from django_celery_beat.schedulers import now as beat_now

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


class DesignSystemAssetTests(SimpleTestCase):
    def test_mobile_nav_toggle_adds_open_class_used_by_css(self) -> None:
        node_path = shutil.which("node")
        if node_path is None:
            self.skipTest("Node.js is required to execute the design-system.js behavior test.")

        project_root = Path(__file__).resolve().parents[1]
        script_path = project_root / "core/static/core/js/design-system.js"
        test_script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");

            class ClassList {
              constructor() {
                this.names = new Set();
              }
              add(...names) {
                names.forEach((name) => this.names.add(name));
              }
              remove(...names) {
                names.forEach((name) => this.names.delete(name));
              }
              contains(name) {
                return this.names.has(name);
              }
              toggle(name, force) {
                const shouldAdd = force === undefined ? !this.names.has(name) : Boolean(force);
                if (shouldAdd) {
                  this.names.add(name);
                } else {
                  this.names.delete(name);
                }
                return shouldAdd;
              }
              value() {
                return Array.from(this.names).sort().join(" ");
              }
            }

            const listeners = {};
            const menu = {
              classList: new ClassList(),
            };
            const trigger = {
              attrs: {
                "data-pg-toggle": "nav",
                "data-pg-target": "#navbarNav",
                "aria-expanded": "false",
              },
              getAttribute(name) {
                return this.attrs[name] || null;
              },
              setAttribute(name, value) {
                this.attrs[name] = String(value);
              },
              closest(selector) {
                if (selector === "[data-pg-toggle], [data-pg-dismiss]") return this;
                return null;
              },
            };

            const document = {
              readyState: "complete",
              body: { classList: new ClassList() },
              querySelector(selector) {
                return selector === "#navbarNav" ? menu : null;
              },
              querySelectorAll() {
                return [];
              },
              addEventListener(type, listener) {
                listeners[type] = listener;
              },
            };
            const window = {
              addEventListener() {},
              getComputedStyle() {
                return { overflow: "visible", overflowX: "visible", overflowY: "visible" };
              },
            };

            vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), { document, window, console });
            listeners.click({ target: trigger, preventDefault() {} });

            if (!menu.classList.contains("pg-open")) {
              throw new Error(`Expected nav menu to receive pg-open; classes: ${menu.classList.value() || "(none)"}`);
            }
            if (menu.classList.contains("pg-show")) {
              throw new Error("Nav menu should not use the collapse-only pg-show class.");
            }
            if (trigger.attrs["aria-expanded"] !== "true") {
              throw new Error(`Expected aria-expanded=true; got ${trigger.attrs["aria-expanded"]}`);
            }
            """
        )

        result = subprocess.run(
            [node_path, "-e", test_script, str(script_path)],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


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
