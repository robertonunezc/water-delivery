from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from django_tenants.utils import schema_context

from clients.models import Client
from clients.services import balance_service
from clients.services.client_service import ClientUpdateData, update_client
from orders.models import Order
from tenant_client.test_utils import TenantTestMixin


class BranchCreditTransferConcurrencyTests(TenantTestMixin, TransactionTestCase):
    def setUp(self) -> None:
        connection.set_schema_to_public()
        schema = f'credit_concurrency_{uuid4().hex[:12]}'
        self.tenant, _ = self.setup_test_tenant(schema, f'{schema.replace("_", "-")}.test.com')
        connection.set_tenant(self.tenant)
        self.corporate = Client.objects.create(
            name='ABC concurrency', type='corporate', credit_limit=Decimal('5000.00'),
        )
        self.branch = Client.objects.create(
            name='XYZ concurrency', corporate=self.corporate, credit_limit=Decimal('5000.00'),
        )
        order = Order.objects.create(client=self.branch, total_amount=Decimal('2000.00'))
        balance_service.add_debt(self.branch, Decimal('2000.00'), reference_order=order)

    def tearDown(self) -> None:
        connection.set_schema_to_public()
        self.tenant.delete(force_drop=True)

    def _fixture_teardown(self) -> None:
        # The dedicated tenant schema is dropped in tearDown; never flush public.
        pass

    def _update_credit(self, client_id: int, data: ClientUpdateData, pids: Queue[int]) -> None:
        worker_connection = connections['default']
        try:
            with schema_context(self.tenant.schema_name):
                with worker_connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    pids.put(cursor.fetchone()[0])
                update_client(Client.objects.get(pk=client_id), data, None)
        finally:
            worker_connection.close()

    def _wait_for_lock(self, pid: int) -> None:
        deadline = monotonic() + 4
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_stat_clear_snapshot()')
                cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', [pid])
                row = cursor.fetchone()
                if row and row[0] == 'Lock':
                    return
            sleep(0.01)
        self.fail('The concurrent credit operation did not reach its expected database lock.')

    def test_corporate_policy_edit_and_branch_switch_do_not_deadlock(self) -> None:
        pids: Queue[int] = Queue()
        with ThreadPoolExecutor(max_workers=2) as executor:
            with transaction.atomic():
                Client.objects.select_for_update().get(pk=self.corporate.pk)
                policy = executor.submit(
                    self._update_credit, self.corporate.pk,
                    ClientUpdateData(credit_limit=Decimal('4500.00')), pids,
                )
                self._wait_for_lock(pids.get(timeout=4))
                switch = executor.submit(
                    self._update_credit, self.branch.pk,
                    ClientUpdateData(credit_override_enabled=True, credit_limit=Decimal('4000.00')), pids,
                )
                self._wait_for_lock(pids.get(timeout=4))
            policy.result(timeout=8)
            switch.result(timeout=8)

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal('0.00'))
        self.assertEqual(self.branch.current_debt, Decimal('2000.00'))
        self.assertEqual(self.corporate.credit_limit, Decimal('4500.00'))
        self.assertEqual(self.branch.credit_limit, Decimal('4000.00'))
