from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context

from clients.models import Client
from clients.services.credit_reconciliation_service import (
    CreditReconciliationSummary,
    get_credit_reconciliation_summary,
)


class Command(BaseCommand):
    help = 'Report clients whose credit ledger does not match open credit orders.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--schema',
            help='Tenant schema to inspect. Defaults to the current connection schema.',
        )
        parser.add_argument(
            '--fail-on-mismatch',
            action='store_true',
            help='Exit with an error when mismatches are found.',
        )

    def handle(self, *args, **options) -> None:
        schema = options.get('schema')
        if schema:
            with schema_context(schema):
                mismatch_count = self._write_report()
        else:
            mismatch_count = self._write_report()

        if options.get('fail_on_mismatch') and mismatch_count:
            raise CommandError(
                f'Found {mismatch_count} credit reconciliation mismatch(es).'
            )

    def _write_report(self) -> int:
        mismatch_count = 0
        clients = (
            Client.objects.filter(active=True)
            .select_related('corporate')
            .order_by('id')
        )
        for client in clients:
            summary = get_credit_reconciliation_summary(client)
            if summary.is_balanced:
                continue
            mismatch_count += 1
            self.stdout.write(self._format_summary(summary))

        if mismatch_count == 0:
            self.stdout.write('No credit reconciliation mismatches found.')
        return mismatch_count

    def _format_summary(self, summary: CreditReconciliationSummary) -> str:
        return (
            f'client={summary.client.id} {summary.client.name} '
            f'credit_account={summary.credit_account.id} '
            f'ledger={summary.ledger_debt:.2f} '
            f'open_orders={summary.open_credit_total:.2f} '
            f'difference={summary.difference:.2f} '
            f'open_order_count={summary.open_order_count}'
        )
