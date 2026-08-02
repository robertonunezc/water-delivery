from datetime import date
import re
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, RequestFactory, SimpleTestCase
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.schedulers import DatabaseScheduler
from django_celery_beat.schedulers import now as beat_now

User = get_user_model()

from .models import Employee
from .admin import EmployeeAdmin
from . import views
from clients.models import Client
from tenant_client.test_utils import FastTenantTestCase


class DesignSystemMigrationTests(SimpleTestCase):
    bootstrap_asset_pattern = re.compile(r"bootstrap(?:\.min)?\.(?:css|js|bundle)", re.IGNORECASE)
    inline_style_pattern = re.compile(r"(<style\b|style=|style\.cssText|\.style\.(?:background|backgroundColor|border|borderRadius|boxShadow|color|display|font|fontSize|fontWeight|margin|opacity|padding|width))")
    class_attribute_pattern = re.compile(r'class="([^"]*)"')
    bootstrap_class_token_pattern = re.compile(
        r"^(?:"
        r"btn(?:-[a-z0-9-]+)?|card(?:-[a-z0-9-]+)?|alert(?:-[a-z0-9-]+)?|badge(?:-[a-z0-9-]+)?|"
        r"navbar(?:-[a-z0-9-]+)?|dropdown(?:-[a-z0-9-]+)?|modal(?:-[a-z0-9-]+)?|"
        r"container(?:-fluid)?|row|col(?:-[a-z0-9-]+)?|form-control|form-select|"
        r"form-check(?:-[a-z0-9-]+)?|form-switch|input-group(?:-[a-z0-9-]+)?|table(?:-[a-z0-9-]+)?|"
        r"nav(?:-[a-z0-9-]+)?|pagination|page-(?:item|link)|jumbotron|"
        r"d-(?:none|flex|grid|block|inline|inline-block)|"
        r"text-(?:primary|secondary|success|danger|warning|info|dark|white|muted|center|end)|"
        r"bg-(?:primary|secondary|success|danger|warning|info|dark|light|white)|"
        r"m[bsteyx]?-[0-5]|p[bsteyx]?-[0-5]|g(?:ap)?-[0-5]|"
        r"justify-content-[a-z-]+|align-items-[a-z-]+|flex-[a-z-]+|"
        r"w-100|h-100|shadow(?:-sm)?|rounded(?:-[a-z]+)?|align-middle"
        r")$",
        re.IGNORECASE,
    )
    allowed_inline_style_fragments = (
        "display:none",
        "display: none",
    )
    legacy_tile_pattern = re.compile(
        r"\b(?:"
        r"dashboard-kpi|kpi-(?:blue|amber|emerald|slate|red)|"
        r"(?:debt|credit|order)-stats-card|(?:debt|credit|order)-stat-(?:item|value|label)|"
        r"stats-card|stat-grid|stat-item|stat-value|stat-label|"
        r"workspace-summary-card|credit-summary-card"
        r")\b"
    )

    def _project_ui_files(self) -> list[Path]:
        roots = [
            settings.BASE_DIR / "core",
            settings.BASE_DIR / "clients",
            settings.BASE_DIR / "orders",
            settings.BASE_DIR / "routes",
            settings.BASE_DIR / "report",
            settings.BASE_DIR / "product",
            settings.BASE_DIR / "invoice",
            settings.BASE_DIR / "tenant_client",
            settings.BASE_DIR / "templates",
        ]
        files: list[Path] = []
        for root in roots:
            for suffix in ("*.html", "*.js", "*.css"):
                files.extend(root.rglob(suffix))
        return [
            file_path
            for file_path in files
            if "migrations" not in file_path.parts
            and "staticfiles" not in file_path.parts
            and "html_template" not in file_path.parts
        ]

    def _project_python_ui_files(self) -> list[Path]:
        roots = [
            settings.BASE_DIR / "clients",
            settings.BASE_DIR / "orders",
            settings.BASE_DIR / "routes",
            settings.BASE_DIR / "product",
            settings.BASE_DIR / "invoice",
            settings.BASE_DIR / "payment",
        ]
        files: list[Path] = []
        for root in roots:
            files.extend(root.rglob("*.py"))
        return [
            file_path
            for file_path in files
            if "migrations" not in file_path.parts
            and "tests" not in file_path.parts
            and "management" not in file_path.parts
        ]

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(settings.BASE_DIR))

    def _bootstrap_class_tokens(self, content: str) -> list[str]:
        offenders: list[str] = []
        for class_attribute in self.class_attribute_pattern.findall(content):
            for token in class_attribute.split():
                if token.startswith("pg-") or token.startswith("fa"):
                    continue
                if token.startswith("{") or token.endswith("}") or "|" in token:
                    continue
                if self.bootstrap_class_token_pattern.match(token):
                    offenders.append(token)
        return offenders

    def test_base_layouts_load_shared_design_system_assets(self) -> None:
        base_templates = [
            settings.BASE_DIR / "core/templates/base.html",
            settings.BASE_DIR / "tenant_client/templates/tenant_client/base_tenant.html",
        ]

        for template_path in base_templates:
            content = template_path.read_text()

            self.assertIn("core/css/design-system.css", content, self._relative(template_path))
            self.assertIn("core/js/design-system.js", content, self._relative(template_path))
            self.assertNotRegex(content, self.bootstrap_asset_pattern, self._relative(template_path))

    def test_project_ui_files_do_not_include_bootstrap_assets_or_inline_styles(self) -> None:
        offenders: list[str] = []
        for file_path in self._project_ui_files():
            content = file_path.read_text()
            inline_matches = [
                match.group(0)
                for match in self.inline_style_pattern.finditer(content)
                if not any(fragment in match.group(0) for fragment in self.allowed_inline_style_fragments)
            ]
            if self.bootstrap_asset_pattern.search(content) or inline_matches:
                offenders.append(self._relative(file_path))

        self.assertEqual(offenders, [])

    def test_templates_do_not_use_bootstrap_utility_or_component_classes(self) -> None:
        offenders: list[str] = []
        for file_path in self._project_ui_files():
            if file_path.suffix != ".html":
                continue
            content = file_path.read_text()
            if self._bootstrap_class_tokens(content):
                offenders.append(self._relative(file_path))

        self.assertEqual(offenders, [])

    def test_python_ui_code_does_not_emit_bootstrap_or_inline_styles(self) -> None:
        old_ui_fragments = (
            "<style",
            "style=",
            "form-control",
            "form-select",
            "form-check-input",
            'class="button"',
        )
        offenders: list[str] = []
        for file_path in self._project_python_ui_files():
            content = file_path.read_text()
            if any(fragment in content for fragment in old_ui_fragments):
                offenders.append(self._relative(file_path))

        self.assertEqual(offenders, [])

    def test_summary_tiles_use_dashboard_metric_card_pattern(self) -> None:
        offenders: list[str] = []
        for file_path in self._project_ui_files():
            content = file_path.read_text()
            if self.legacy_tile_pattern.search(content):
                offenders.append(self._relative(file_path))

        self.assertEqual(offenders, [])


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


class HomeDashboardRoutingTests(FastTenantTestCase):
    def _create_employee_user(self, *, username: str, position: str) -> User:
        user = User.objects.create_user(
            username=username,
            password="testpass123",
            is_staff=position == "manager",
        )
        Employee.objects.create(
            user=user,
            nombre=username.title(),
            apellidos="Dashboard",
            curp=f"{username[:8].upper():0<18}",
            rfc=f"{username[:8].upper():0<13}",
            street_number="Calle 1",
            position=position,
        )
        return user

    def test_anonymous_user_keeps_public_home(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")
        self.assertContains(response, "PuriGest")

    def test_driver_employee_uses_delivery_dashboard(self) -> None:
        user = self._create_employee_user(username="driveruser", position="driver")
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "delivery_dashboard.html")
        self.assertContains(response, "Panel del repartidor")

    def test_staff_employee_uses_delivery_dashboard(self) -> None:
        user = self._create_employee_user(username="staffuser", position="staff")
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "delivery_dashboard.html")
        self.assertContains(response, "Panel del repartidor")

    def test_manager_employee_uses_manager_dashboard(self) -> None:
        user = self._create_employee_user(username="manageruser", position="manager")
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "manager_dashboard.html")
        self.assertContains(response, "Dashboard Backoffice")

    def test_user_without_employee_keeps_current_home(self) -> None:
        user = User.objects.create_user(username="noemployee", password="testpass123")
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")
        self.assertContains(response, "Panel Principal")


class DeliveryDashboardContextTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="deliveryuser", password="testpass123")
        Employee.objects.create(
            user=self.user,
            nombre="Delivery",
            apellidos="Dashboard",
            curp="DELIVERYUSER00000",
            rfc="DELIVERY00000",
            street_number="Calle 1",
            position="driver",
        )

    def test_delivery_dashboard_actions_are_ordered(self) -> None:
        from core.services.dashboard_service import get_delivery_dashboard_context

        context = get_delivery_dashboard_context(user=self.user, today=date(2026, 7, 1))

        self.assertEqual(
            [action["key"] for action in context["dashboard_actions"]],
            [
                "route",
                "future_reminders",
                "outside_route_sales",
                "credits",
                "day_close",
            ],
        )

    def test_future_reminders_action_is_disabled(self) -> None:
        from core.services.dashboard_service import get_delivery_dashboard_context

        context = get_delivery_dashboard_context(user=self.user, today=date(2026, 7, 1))
        reminders_action = context["dashboard_actions"][1]

        self.assertEqual(reminders_action["key"], "future_reminders")
        self.assertFalse(reminders_action["is_enabled"])
        self.assertEqual(reminders_action["status_label"], "Próximamente")

    def test_day_close_action_uses_selected_local_date(self) -> None:
        from core.services.dashboard_service import get_delivery_dashboard_context

        context = get_delivery_dashboard_context(user=self.user, today=date(2026, 7, 1))
        day_close_action = context["dashboard_actions"][4]

        self.assertEqual(day_close_action["key"], "day_close")
        self.assertEqual(
            day_close_action["url"],
            f"{reverse('report:breakdown_payment_method')}?date=2026-07-01",
        )
        self.assertIn("Inventario", day_close_action["meta"])

    def test_credits_action_counts_clients_with_debt(self) -> None:
        from core.services.dashboard_service import get_delivery_dashboard_context

        Client.objects.create(name="Con deuda 1", current_debt="10.00", active=True)
        Client.objects.create(name="Con deuda 2", current_debt="25.00", active=True)
        Client.objects.create(name="Sin deuda", current_debt="0.00", active=True)

        context = get_delivery_dashboard_context(user=self.user, today=date(2026, 7, 1))
        credits_action = context["dashboard_actions"][3]

        self.assertEqual(credits_action["key"], "credits")
        self.assertEqual(credits_action["badge_count"], 2)
        self.assertEqual(credits_action["url"], reverse("report:credit_report"))
