from datetime import date

from django.test import SimpleTestCase


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
