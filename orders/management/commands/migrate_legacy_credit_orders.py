from dataclasses import dataclass
from typing import Iterable

from django.core.management.base import BaseCommand
from django.db import transaction

from orders.models import Order
from payment.models import Payment


@dataclass
class MigrationCounters:
    scanned_orders: int = 0
    migrated_orders: int = 0
    updated_payments: int = 0
    skipped_existing_pending: int = 0
    skipped_multiple_legacy: int = 0


class Command(BaseCommand):
    help = (
        'Migrate legacy credit payments to the new credit-order flow '
        '(order.type=credito and payment method/status pending_credit/pending).'
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Persist changes. Without this flag, the command only reports what would change.',
        )
        parser.add_argument(
            '--order-id',
            type=int,
            help='Limit migration to a single order id.',
        )

    def handle(self, *args, **options) -> None:
        apply_changes = options['apply']
        order_id = options.get('order_id')

        orders = self._get_target_orders(order_id=order_id)
        counters = MigrationCounters(scanned_orders=orders.count())

        if not apply_changes:
            self.stdout.write(self.style.WARNING('Dry run mode. No changes will be written.'))

        for order in orders:
            self._process_order(order=order, apply_changes=apply_changes, counters=counters)

        self._print_summary(counters=counters, apply_changes=apply_changes)

    def _get_target_orders(self, order_id: int | None) -> Iterable[Order]:
        orders = Order.objects.filter(payments__method='credit').distinct().prefetch_related('payments')
        if order_id is not None:
            orders = orders.filter(pk=order_id)
        return orders.order_by('id')

    def _process_order(
        self,
        order: Order,
        apply_changes: bool,
        counters: MigrationCounters,
    ) -> None:
        legacy_credit_payments = [payment for payment in order.payments.all() if payment.method == 'credit']
        existing_pending_credit = any(
            payment.method == 'pending_credit' for payment in order.payments.all()
        )

        if existing_pending_credit:
            counters.skipped_existing_pending += 1
            self.stdout.write(
                self.style.WARNING(
                    f'Skipping order #{order.id}: it already has a pending_credit payment.'
                )
            )
            return

        if len(legacy_credit_payments) != 1:
            counters.skipped_multiple_legacy += 1
            self.stdout.write(
                self.style.WARNING(
                    f'Skipping order #{order.id}: expected exactly 1 legacy credit payment, '
                    f'found {len(legacy_credit_payments)}.'
                )
            )
            return

        payment = legacy_credit_payments[0]

        self.stdout.write(
            f'Order #{order.id}: type {order.type!r} -> \'credito\', '
            f'payment #{payment.id}: method {payment.method!r} -> \'pending_credit\', '
            f'status {payment.status!r} -> \'pending\''
        )

        if not apply_changes:
            counters.migrated_orders += 1
            counters.updated_payments += 1
            return

        with transaction.atomic():
            if order.type != 'credito':
                order.type = 'credito'
                order.save(update_fields=['type', 'updated_at'])

            payment.method = 'pending_credit'
            payment.status = 'pending'
            payment.save(update_fields=['method', 'status', 'updated_at'], apply_accounting=False)

        counters.migrated_orders += 1
        counters.updated_payments += 1

    def _print_summary(self, counters: MigrationCounters, apply_changes: bool) -> None:
        mode = 'Applied' if apply_changes else 'Planned'
        self.stdout.write('')
        self.stdout.write(f'{mode} migration summary:')
        self.stdout.write(f'  Orders scanned: {counters.scanned_orders}')
        self.stdout.write(f'  Orders migrated: {counters.migrated_orders}')
        self.stdout.write(f'  Payments updated: {counters.updated_payments}')
        self.stdout.write(
            f'  Skipped with existing pending_credit payment: {counters.skipped_existing_pending}'
        )
        self.stdout.write(
            f'  Skipped with ambiguous legacy credit payments: {counters.skipped_multiple_legacy}'
        )