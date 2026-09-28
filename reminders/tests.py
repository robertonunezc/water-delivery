from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from tenant_client.test_utils import FastTenantTestCase

from reminders.models import Reminder


User = get_user_model()


class ReminderQuerySetTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="ana", password="testpass")
        self.other_user = User.objects.create_user(username="luis", password="testpass")
        self.today = date(2026, 9, 28)

    def _reminder(self, title: str, **kwargs) -> Reminder:
        defaults = {"created_by": self.user}
        defaults.update(kwargs)
        return Reminder.objects.create(title=title, **defaults)

    def test_active_excludes_completed_and_deleted(self) -> None:
        active = self._reminder("Activo")
        completed = self._reminder("Listo", completed_at=timezone.now(), completed_by=self.user)
        deleted = self._reminder("Eliminado")
        deleted.delete()

        reminders = list(Reminder.objects.active())

        self.assertIn(active, reminders)
        self.assertNotIn(completed, reminders)
        self.assertNotIn(deleted, reminders)

    def test_overdue_finds_incomplete_past_dated_reminders(self) -> None:
        overdue = self._reminder("Vencido", reminder_date=self.today - timedelta(days=1))
        self._reminder("Hoy", reminder_date=self.today)
        self._reminder("Futuro", reminder_date=self.today + timedelta(days=1))
        self._reminder(
            "Vencido listo",
            reminder_date=self.today - timedelta(days=1),
            completed_at=timezone.now(),
            completed_by=self.user,
        )

        reminders = list(Reminder.objects.overdue(self.today))

        self.assertEqual(reminders, [overdue])

    def test_completed_returns_completed_non_deleted_reminders(self) -> None:
        completed = self._reminder("Listo", completed_at=timezone.now(), completed_by=self.user)
        deleted_completed = self._reminder(
            "Listo eliminado",
            completed_at=timezone.now(),
            completed_by=self.user,
        )
        deleted_completed.delete()
        self._reminder("Activo")

        reminders = list(Reminder.objects.completed())

        self.assertEqual(reminders, [completed])

    def test_for_user_scopes_to_creator(self) -> None:
        mine = self._reminder("Mio")
        Reminder.objects.create(title="De otra persona", created_by=self.other_user)

        reminders = list(Reminder.objects.for_user(self.user))

        self.assertEqual(reminders, [mine])

    def test_urgent_first_orders_urgent_before_normal(self) -> None:
        normal = self._reminder("Normal", urgent=False)
        urgent = self._reminder("Urgente", urgent=True)

        reminders = list(Reminder.objects.urgent_first())

        self.assertEqual(reminders, [urgent, normal])


class ReminderModelTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="ana", password="testpass")
        self.other_user = User.objects.create_user(username="luis", password="testpass")

    def test_mark_completed_sets_timestamp_and_user(self) -> None:
        completed_at = timezone.now()
        reminder = Reminder.objects.create(title="Recoger garrafones", created_by=self.user)

        reminder.mark_completed(self.other_user, completed_at=completed_at)

        reminder.refresh_from_db()
        self.assertEqual(reminder.completed_by, self.other_user)
        self.assertEqual(reminder.completed_at, completed_at)

        reminder.mark_completed(self.user, completed_at=completed_at + timedelta(days=1))

        reminder.refresh_from_db()
        self.assertEqual(reminder.completed_by, self.other_user)
        self.assertEqual(reminder.completed_at, completed_at)
