from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from clients.models import Address, Client
from core.models import Employee, Transport
from routes.models import Route, RouteClient
from tenant_client.test_utils import FastTenantTestCase

from reminders.models import Reminder
from reminders.services import (
    complete_reminder,
    get_home_reminder_context,
    get_user_route_client_ids,
    soft_delete_reminder,
)


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


class ReminderHomeServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="ana_routes", password="testpass")
        self.other_user = User.objects.create_user(username="luis_routes", password="testpass")
        self.today = date.today()
        self.routed_client = self._create_client("Cliente en ruta")
        self.outside_client = self._create_client("Cliente fuera de ruta")
        self.employee = Employee.objects.create(
            user=self.user,
            nombre="Ana",
            apellidos="Ruta",
            curp="CURPANA000000001",
            rfc="RFCANA000001",
            street_number="Calle Ruta 1",
            position="driver",
        )
        self.transport = Transport.objects.create(
            license_plate="REM-001",
            model="Unidad recordatorios",
            capacity_liters=1000,
            assigned_driver=self.employee,
            is_active=True,
        )
        self.route = Route.objects.create(
            name="Ruta de hoy",
            transportation=self.transport,
            weekday=self.today.strftime("%A").lower(),
            is_active=True,
        )
        RouteClient.objects.create(
            route=self.route,
            client=self.routed_client,
            sequence=1,
            interval_weeks=1,
            anchor_date=self.today,
            is_active=True,
        )

    def _create_client(self, name: str) -> Client:
        client = Client.objects.create(name=name)
        Address.objects.create(client=client, type="delivery", street=f"Calle {name}")
        return client

    def _reminder(self, title: str, **kwargs) -> Reminder:
        defaults = {"created_by": self.user}
        defaults.update(kwargs)
        return Reminder.objects.create(title=title, **defaults)

    def test_no_date_no_client_reminder_appears_today(self) -> None:
        reminder = self._reminder("Llamar a Maria")
        other_user_reminder = Reminder.objects.create(
            title="Recordatorio ajeno",
            created_by=self.other_user,
        )

        context = get_home_reminder_context(self.user, today=self.today)

        self.assertIn(reminder, context["today_reminders"])
        self.assertNotIn(other_user_reminder, context["today_reminders"])
        self.assertEqual(context["route_context_reminders"], [])

    def test_today_dated_reminder_appears_today(self) -> None:
        reminder = self._reminder("Vender 3 garrafones", reminder_date=self.today)

        context = get_home_reminder_context(self.user, today=self.today)

        self.assertEqual(context["today_reminders"], [reminder])
        self.assertEqual(context["route_context_reminders"], [])

    def test_past_dated_reminder_is_excluded_from_home(self) -> None:
        self._reminder(
            "Vencido con cliente",
            client=self.routed_client,
            reminder_date=self.today - timedelta(days=1),
        )

        context = get_home_reminder_context(self.user, today=self.today)

        self.assertEqual(context["today_reminders"], [])
        self.assertEqual(context["route_context_reminders"], [])

    def test_client_only_reminder_appears_when_client_is_in_user_route(self) -> None:
        reminder = self._reminder("Recoger garrafones", client=self.routed_client)
        self._reminder("Cliente fuera de ruta", client=self.outside_client)

        context = get_home_reminder_context(self.user, today=self.today)

        self.assertEqual(context["today_reminders"], [reminder])
        self.assertEqual(context["route_context_reminders"], [])

    def test_future_client_route_reminder_is_route_context_only(self) -> None:
        reminder = self._reminder(
            "Visita futura",
            client=self.routed_client,
            reminder_date=self.today + timedelta(days=3),
        )

        context = get_home_reminder_context(self.user, today=self.today)

        self.assertEqual(context["today_reminders"], [])
        self.assertEqual(context["route_context_reminders"], [reminder])

    def test_route_lookup_without_employee_transport_or_route_is_empty(self) -> None:
        no_employee_user = User.objects.create_user(username="sin_empleado", password="testpass")
        no_transport_user = User.objects.create_user(username="sin_transporte", password="testpass")
        Employee.objects.create(
            user=no_transport_user,
            nombre="Sin",
            apellidos="Transporte",
            curp="CURPSIN000000001",
            rfc="RFCSIN000001",
            street_number="Calle Sin 1",
            position="driver",
        )
        no_route_user = User.objects.create_user(username="sin_ruta", password="testpass")
        no_route_employee = Employee.objects.create(
            user=no_route_user,
            nombre="Sin",
            apellidos="Ruta",
            curp="CURPRUT000000001",
            rfc="RFCRUT000001",
            street_number="Calle Ruta 2",
            position="driver",
        )
        Transport.objects.create(
            license_plate="REM-002",
            model="Unidad sin ruta",
            capacity_liters=1000,
            assigned_driver=no_route_employee,
            is_active=True,
        )

        self.assertEqual(get_user_route_client_ids(self.user, self.today), {self.routed_client.id})
        self.assertEqual(get_user_route_client_ids(no_employee_user, self.today), set())
        self.assertEqual(get_user_route_client_ids(no_transport_user, self.today), set())
        self.assertEqual(get_user_route_client_ids(no_route_user, self.today), set())


class ReminderServiceActionTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.owner = User.objects.create_user(username="owner", password="testpass")
        self.other_user = User.objects.create_user(username="other", password="testpass")

    def test_complete_reminder_requires_owner(self) -> None:
        reminder = Reminder.objects.create(title="Solo mio", created_by=self.owner)

        with self.assertRaises(PermissionDenied):
            complete_reminder(reminder, self.other_user)

        reminder.refresh_from_db()
        self.assertIsNone(reminder.completed_at)
        self.assertIsNone(reminder.completed_by)

        completed = complete_reminder(reminder, self.owner)

        completed.refresh_from_db()
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(completed.completed_by, self.owner)

    def test_soft_delete_reminder_requires_owner(self) -> None:
        reminder = Reminder.objects.create(title="Eliminar mio", created_by=self.owner)

        with self.assertRaises(PermissionDenied):
            soft_delete_reminder(reminder, self.other_user)

        reminder.refresh_from_db()
        self.assertIsNone(reminder.deleted_at)

        soft_delete_reminder(reminder, self.owner)

        reminder = Reminder.all_objects.get(pk=reminder.pk)
        self.assertIsNotNone(reminder.deleted_at)
        self.assertFalse(Reminder.objects.filter(pk=reminder.pk).exists())
