from datetime import date
import json
import re
import subprocess
from types import SimpleNamespace
import unicodedata
from unittest.mock import patch

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase

from core import views


def strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


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


class CubicStaticAssetTests(SimpleTestCase):
    required_assets = [
        "core/vendor/cubic/bootstrap/dist/css/bootstrap.min.css",
        "core/vendor/cubic/bootstrap/dist/js/bootstrap.min.js",
        "core/vendor/cubic/bootstrap/dist/fonts/glyphicons-halflings-regular.woff2",
        "core/vendor/cubic/css/style.css",
        "core/vendor/cubic/css/spinners.css",
        "core/vendor/cubic/css/animate.css",
        "core/vendor/cubic/css/colors/default.css",
        "core/vendor/cubic/js/custom.js",
        "core/vendor/cubic/js/sidebarmenu.js",
        "core/vendor/cubic/js/jquery.slimscroll.js",
        "core/vendor/cubic/js/waves.js",
        "core/vendor/cubic/plugins/components/jquery/dist/jquery.min.js",
        "core/vendor/cubic/plugins/images/favicon.png",
        "core/vendor/cubic/plugins/images/login-register.jpg",
        "core/vendor/cubic/less/icons/simple-line-icons/fonts/Simple-Line-Icons.woff2",
        "core/vendor/cubic/less/icons/themify-icons/fonts/themify.woff",
        "core/vendor/cubic/less/icons/font-awesome/fonts/fontawesome-webfont.woff2",
        "core/vendor/cubic/less/icons/material-design-iconic-font/css/materialdesignicons.min.css",
        "core/vendor/cubic/less/icons/material-design-iconic-font/fonts/materialdesignicons-webfont.woff2",
        "core/css/cubic-overrides.css",
    ]

    def test_required_cubic_assets_are_checked_in(self) -> None:
        for asset in self.required_assets:
            with self.subTest(asset=asset):
                asset_path = settings.BASE_DIR / "core/static" / asset
                self.assertTrue(asset_path.exists())
                git_result = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", f"core/static/{asset}"],
                    cwd=settings.BASE_DIR,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(git_result.returncode, 0, git_result.stderr)

    def test_project_templates_do_not_reference_html_template(self) -> None:
        template_paths = settings.BASE_DIR.glob("**/templates/**/*.html")
        offenders = [
            path
            for path in template_paths
            if "html_template/" in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(offenders, [])

    def test_templates_do_not_mix_bootstrap_and_pg_toggle_on_same_tag(self) -> None:
        pattern = re.compile(
            r"<[^>]*(data-toggle=)[^>]*(data-pg-toggle=)|"
            r"<[^>]*(data-pg-toggle=)[^>]*(data-toggle=)",
            re.DOTALL,
        )
        offenders = []
        for path in settings.BASE_DIR.glob("**/templates/**/*.html"):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(path.relative_to(settings.BASE_DIR)))

        self.assertEqual(offenders, [])


class CubicBaseTemplateTests(SimpleTestCase):
    def base_template(self) -> str:
        return (settings.BASE_DIR / "core/templates/base.html").read_text(encoding="utf-8")

    def test_base_links_cubic_css_before_design_system(self) -> None:
        content = self.base_template()
        self.assertLess(
            content.index("core/vendor/cubic/bootstrap/dist/css/bootstrap.min.css"),
            content.index("core/css/design-system.css"),
        )
        self.assertLess(
            content.index("core/vendor/cubic/css/style.css"),
            content.index("core/css/design-system.css"),
        )
        self.assertLess(
            content.index("core/css/design-system.css"),
            content.index("core/css/cubic-overrides.css"),
        )

    def test_base_links_scripts_in_dependency_order(self) -> None:
        content = self.base_template()
        expected = [
            "core/vendor/cubic/plugins/components/jquery/dist/jquery.min.js",
            "core/vendor/cubic/bootstrap/dist/js/bootstrap.min.js",
            "core/vendor/cubic/js/sidebarmenu.js",
            "core/vendor/cubic/js/jquery.slimscroll.js",
            "core/vendor/cubic/js/waves.js",
            "core/vendor/cubic/js/custom.js",
            "core/js/design-system.js",
            "{% block extra_js %}",
        ]
        positions = [content.index(item) for item in expected]
        self.assertEqual(positions, sorted(positions))

    def test_base_uses_cubic_shell_structure(self) -> None:
        content = self.base_template()
        self.assertIn('id="wrapper"', content)
        self.assertIn('class="navbar-header"', content)
        self.assertIn('class="sidebar"', content)
        self.assertIn('id="side-menu"', content)
        self.assertIn('class="page-wrapper"', content)

    def test_base_preserves_required_template_blocks(self) -> None:
        content = self.base_template()
        for block in ["title", "extra_css", "content", "extra_js"]:
            self.assertIn(f"{{% block {block} %}}", content)

    def test_base_keeps_fontawesome_6_for_existing_icons(self) -> None:
        self.assertIn(
            "cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css",
            self.base_template(),
        )

    def test_base_keeps_logout_as_post_with_csrf(self) -> None:
        content = self.base_template()
        self.assertIn('method="post"', content)
        self.assertIn("{% csrf_token %}", content)
        self.assertIn("{% url 'core:logout' %}", content)

    def test_base_has_no_sample_cubic_content(self) -> None:
        content = self.base_template()
        for sample in [
            "Hanna Gover",
            "Buy Cubic Admin",
            "See all notifications",
            "Task 1",
            "eCommerce",
        ]:
            self.assertNotIn(sample, content)


class CubicAuthTemplateTests(SimpleTestCase):
    def auth_base_template(self) -> str:
        return (settings.BASE_DIR / "core/templates/base_auth.html").read_text(encoding="utf-8")

    def login_template(self) -> str:
        return (
            settings.BASE_DIR / "core/templates/registration/login.html"
        ).read_text(encoding="utf-8")

    def test_login_extends_base_auth(self) -> None:
        self.assertIn("{% extends 'base_auth.html' %}", self.login_template())

    def test_auth_base_links_cubic_assets_without_sidebar(self) -> None:
        content = self.auth_base_template()
        self.assertIn("core/vendor/cubic/bootstrap/dist/css/bootstrap.min.css", content)
        self.assertIn("core/vendor/cubic/css/style.css", content)
        self.assertIn("core/vendor/cubic/js/custom.js", content)
        self.assertIn("{% block content %}", content)
        self.assertNotIn('id="side-menu"', content)
        self.assertNotIn('class="sidebar"', content)

    def test_login_preserves_django_auth_fields(self) -> None:
        content = self.login_template()
        self.assertIn("{% csrf_token %}", content)
        self.assertIn('name="{{ form.username.name }}"', content)
        self.assertIn('name="{{ form.password.name }}"', content)
        self.assertIn('name="next"', content)
        self.assertIn("{{ next }}", content)

    def test_login_uses_spanish_copy_and_no_cubic_sample_links(self) -> None:
        content = self.login_template()
        self.assertIn("Iniciar Sesion", strip_accents(content))
        self.assertIn("Usuario", content)
        self.assertIn("Contrasena", strip_accents(content))
        for sample in ["Forgot pwd", "Facebook", "Google", "register.html", "Sign Up"]:
            self.assertNotIn(sample, content)



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
