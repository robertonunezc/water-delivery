from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.urls import reverse
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

    def test_route_lookup_uses_target_date_for_route_weekday(self) -> None:
        target_date = date.today() + timedelta(days=2)
        target_client = self._create_client("Cliente fecha objetivo")
        target_route = Route.objects.create(
            name="Ruta fecha objetivo",
            transportation=self.transport,
            weekday=target_date.strftime("%A").lower(),
            is_active=True,
        )
        RouteClient.objects.create(
            route=target_route,
            client=target_client,
            sequence=2,
            interval_weeks=1,
            anchor_date=target_date,
            is_active=True,
        )

        route_client_ids = get_user_route_client_ids(self.user, target_date)

        self.assertIn(target_client.id, route_client_ids)


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


class ReminderViewTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="view_owner", password="testpass")
        self.other_user = User.objects.create_user(username="view_other", password="testpass")
        self.today = timezone.localdate()
        self.client_record = self._create_client("Maria")
        self.other_client = self._create_client("Jose")

    def _create_client(self, name: str) -> Client:
        client = Client.objects.create(name=name)
        Address.objects.create(client=client, type="delivery", street=f"Calle {name}")
        return client

    def _reminder(self, title: str, **kwargs) -> Reminder:
        defaults = {"created_by": self.user}
        defaults.update(kwargs)
        return Reminder.objects.create(title=title, **defaults)

    def test_create_requires_authentication(self) -> None:
        response = self.client.get(reverse("reminders:create"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("core:login"), response.url)

    def test_create_sets_created_by_and_redirects_home(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("reminders:create"),
            {
                "title": "Vender 3 garrafones",
                "description": "En la proxima visita",
                "client": self.client_record.pk,
                "reminder_date": (self.today + timedelta(days=2)).isoformat(),
                "urgent": "on",
            },
        )

        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        reminder = Reminder.objects.get(title="Vender 3 garrafones")
        self.assertEqual(reminder.created_by, self.user)
        self.assertEqual(reminder.client, self.client_record)
        self.assertTrue(reminder.urgent)

    def test_create_with_client_query_preselects_client(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('reminders:create')}?client={self.client_record.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["client"].value(), self.client_record.pk)

    def test_create_with_invalid_client_query_does_not_fail(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('reminders:create')}?client=999999")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["form"]["client"].value())

    def test_create_allows_inactive_non_deleted_client(self) -> None:
        inactive_client = self._create_client("Cliente inactivo")
        inactive_client.active = False
        inactive_client.save(update_fields=["active"])
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("reminders:create"),
            {
                "title": "Visitar cliente inactivo",
                "description": "",
                "client": inactive_client.pk,
                "reminder_date": "",
            },
        )

        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        reminder = Reminder.objects.get(title="Visitar cliente inactivo")
        self.assertEqual(reminder.client, inactive_client)

    def test_list_default_shows_active_future_and_no_date_only(self) -> None:
        self.client.force_login(self.user)
        no_date = self._reminder("Sin fecha")
        future = self._reminder("Futuro", reminder_date=self.today + timedelta(days=2))
        self._reminder("Vencido", reminder_date=self.today - timedelta(days=1))
        self._reminder("Listo", completed_at=timezone.now(), completed_by=self.user)
        deleted = self._reminder("Eliminado")
        deleted.delete()
        Reminder.objects.create(title="Ajeno", created_by=self.other_user)

        response = self.client.get(reverse("reminders:list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["reminders"]), [future, no_date])

    def test_list_vencidos_filter_shows_past_incomplete(self) -> None:
        self.client.force_login(self.user)
        overdue = self._reminder("Vencido", reminder_date=self.today - timedelta(days=1))
        self._reminder("Futuro", reminder_date=self.today + timedelta(days=1))
        self._reminder(
            "Vencido listo",
            reminder_date=self.today - timedelta(days=1),
            completed_at=timezone.now(),
            completed_by=self.user,
        )

        response = self.client.get(f"{reverse('reminders:list')}?status=vencidos")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["reminders"]), [overdue])

    def test_list_listos_filter_shows_completed_read_only(self) -> None:
        self.client.force_login(self.user)
        completed = self._reminder("Listo", completed_at=timezone.now(), completed_by=self.user)
        self._reminder("Activo")

        response = self.client.get(f"{reverse('reminders:list')}?status=listos")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["reminders"]), [completed])
        self.assertNotContains(response, reverse("reminders:edit", kwargs={"pk": completed.pk}))

    def test_search_filters_title_and_description(self) -> None:
        self.client.force_login(self.user)
        title_match = self._reminder("Recoger garrafones")
        description_match = self._reminder("Llamar", description="Pedir envases")
        self._reminder("Cobrar factura")

        response = self.client.get(f"{reverse('reminders:list')}?q=garrafones")
        self.assertEqual(list(response.context["reminders"]), [title_match])

        response = self.client.get(f"{reverse('reminders:list')}?q=envases")
        self.assertEqual(list(response.context["reminders"]), [description_match])

    def test_client_filter_limits_results(self) -> None:
        self.client.force_login(self.user)
        maria_reminder = self._reminder("Maria", client=self.client_record)
        self._reminder("Jose", client=self.other_client)

        response = self.client.get(
            f"{reverse('reminders:list')}?client={self.client_record.pk}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["reminders"]), [maria_reminder])

    def test_edit_is_owner_only(self) -> None:
        reminder = self._reminder("Original")
        self.client.force_login(self.other_user)

        response = self.client.post(
            reverse("reminders:edit", kwargs={"pk": reminder.pk}),
            {"title": "Cambiado"},
        )

        reminder.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(reminder.title, "Original")

    def test_completed_reminder_cannot_be_edited(self) -> None:
        self.client.force_login(self.user)
        reminder = self._reminder(
            "Listo",
            completed_at=timezone.now(),
            completed_by=self.user,
        )

        response = self.client.post(
            reverse("reminders:edit", kwargs={"pk": reminder.pk}),
            {"title": "Cambiado"},
        )

        reminder.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(reminder.title, "Listo")

    def test_edit_allows_existing_inactive_non_deleted_client(self) -> None:
        inactive_client = self._create_client("Cliente inactivo en edicion")
        inactive_client.active = False
        inactive_client.save(update_fields=["active"])
        reminder = self._reminder("Original inactivo", client=inactive_client)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("reminders:edit", kwargs={"pk": reminder.pk}),
            {
                "title": "Actualizado inactivo",
                "description": "",
                "client": inactive_client.pk,
                "reminder_date": "",
            },
        )

        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        reminder.refresh_from_db()
        self.assertEqual(reminder.title, "Actualizado inactivo")
        self.assertEqual(reminder.client, inactive_client)

    def test_complete_action_sets_completed_fields(self) -> None:
        self.client.force_login(self.user)
        reminder = self._reminder("Completar")

        response = self.client.post(
            reverse("reminders:complete", kwargs={"pk": reminder.pk}),
            HTTP_REFERER=reverse("reminders:list"),
        )

        self.assertRedirects(response, reverse("reminders:list"), fetch_redirect_response=False)
        reminder.refresh_from_db()
        self.assertIsNotNone(reminder.completed_at)
        self.assertEqual(reminder.completed_by, self.user)

    def test_complete_action_rejects_external_referer_redirect(self) -> None:
        self.client.force_login(self.user)
        reminder = self._reminder("Completar seguro")

        response = self.client.post(
            reverse("reminders:complete", kwargs={"pk": reminder.pk}),
            HTTP_REFERER="https://example.invalid/steal",
        )

        self.assertRedirects(response, reverse("reminders:list"), fetch_redirect_response=False)

    def test_delete_action_soft_deletes(self) -> None:
        self.client.force_login(self.user)
        reminder = self._reminder("Eliminar")

        response = self.client.post(
            reverse("reminders:delete", kwargs={"pk": reminder.pk}),
            HTTP_REFERER=reverse("reminders:list"),
        )

        self.assertRedirects(response, reverse("reminders:list"), fetch_redirect_response=False)
        reminder = Reminder.all_objects.get(pk=reminder.pk)
        self.assertIsNotNone(reminder.deleted_at)

    def test_other_user_cannot_complete_or_delete(self) -> None:
        reminder_to_complete = self._reminder("Completar ajeno")
        reminder_to_delete = self._reminder("Eliminar ajeno")
        self.client.force_login(self.other_user)

        complete_response = self.client.post(
            reverse("reminders:complete", kwargs={"pk": reminder_to_complete.pk})
        )
        delete_response = self.client.post(
            reverse("reminders:delete", kwargs={"pk": reminder_to_delete.pk})
        )

        reminder_to_complete.refresh_from_db()
        reminder_to_delete.refresh_from_db()
        self.assertEqual(complete_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertIsNone(reminder_to_complete.completed_at)
        self.assertIsNone(reminder_to_delete.deleted_at)


class ReminderTemplateIntegrationTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="template_owner", password="testpass")
        self.client_record = self._create_client("Maria Plantilla")

    def _create_client(self, name: str) -> Client:
        client = Client.objects.create(name=name)
        Address.objects.create(client=client, type="delivery", street=f"Calle {name}")
        return client

    def _create_employee(self, user, position: str) -> Employee:
        return Employee.objects.create(
            user=user,
            nombre="Empleado",
            apellidos=position,
            curp=f"CURP{user.pk:014d}",
            rfc=f"RFC{user.pk:010d}",
            street_number="Calle Panel 1",
            position=position,
        )

    def _reminder(self, title: str, **kwargs) -> Reminder:
        defaults = {"created_by": self.user}
        defaults.update(kwargs)
        return Reminder.objects.create(title=title, **defaults)

    def test_base_navigation_contains_recordatorios_links_for_authenticated_user(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("reminders:list"))

        self.assertContains(response, 'href="/recordatorios/"')
        self.assertContains(response, "Recordatorios")
        self.assertContains(response, 'href="/recordatorios/nuevo/"')
        self.assertContains(response, "NUEVO RECORDATORIO")

    def test_home_renders_reminder_block_above_dashboard_actions(self) -> None:
        self.client.force_login(self.user)
        self._reminder("Recoger garrafones")

        response = self.client.get(reverse("core:home"))
        content = response.content.decode()

        self.assertContains(response, "Recordatorios Para Hoy")
        self.assertContains(response, "Recoger garrafones")
        self.assertLess(content.index("Recordatorios Para Hoy"), content.index("Nuevo Pedido"))

    def test_delivery_dashboard_renders_reminder_block(self) -> None:
        self._create_employee(self.user, "driver")
        self.client.force_login(self.user)
        self._reminder("Vender garrafones en ruta")

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "Recordatorios Para Hoy")
        self.assertContains(response, "Vender garrafones en ruta")

    def test_manager_dashboard_renders_reminder_block(self) -> None:
        manager = User.objects.create_user(
            username="template_manager",
            password="testpass",
            is_staff=True,
        )
        self._create_employee(manager, "manager")
        Reminder.objects.create(title="Revisar cobranza", created_by=manager)
        self.client.force_login(manager)

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "Recordatorios Para Hoy")
        self.assertContains(response, "Revisar cobranza")

    def test_client_detail_has_new_reminder_link_with_client_query(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("clients:detail", kwargs={"pk": self.client_record.pk}))

        self.assertContains(response, "NUEVO RECORDATORIO")
        self.assertContains(
            response,
            f'{reverse("reminders:create")}?client={self.client_record.pk}',
        )

    def test_urgent_reminder_renders_urgent_badge(self) -> None:
        self.client.force_login(self.user)
        self._reminder("Urgente visible", urgent=True)

        response = self.client.get(reverse("reminders:list"))

        self.assertContains(response, "Urgente visible")
        self.assertContains(response, "Urgente")

    def test_completed_list_rows_do_not_show_edit_link(self) -> None:
        self.client.force_login(self.user)
        completed = self._reminder(
            "Recordatorio listo",
            completed_at=timezone.now(),
            completed_by=self.user,
        )

        response = self.client.get(f"{reverse('reminders:list')}?status=listos")

        self.assertContains(response, "Recordatorio listo")
        self.assertContains(response, "Solo lectura")
        self.assertNotContains(response, reverse("reminders:edit", kwargs={"pk": completed.pk}))
