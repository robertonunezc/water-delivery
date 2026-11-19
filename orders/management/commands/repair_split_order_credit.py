from contextlib import nullcontext
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Q
from django_tenants.utils import schema_context

from orders.models import Order
from orders.services.order_split_service import OrderSplitError, repair_split_order_credit
from payment.models import Payment


class Command(BaseCommand):
    help = "Repair pending credit left on an original order by the legacy split flow."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--order-id", type=int, required=True, help="Original order ID.")
        parser.add_argument("--schema", help="Tenant schema containing the order.")
        parser.add_argument(
            "--apply", action="store_true",
            help="Persist the repair; defaults to dry run.",
        )

    def handle(self, *args: str, **options: Any) -> None:
        context = schema_context(options["schema"]) if options["schema"] else nullcontext()
        try:
            with context, transaction.atomic():
                order = Order.objects.get(pk=options["order_id"])
                count = repair_split_order_credit(order)
                child_ids = order.split_as_source.values("child_order_id")
                markers = list(Payment.objects.filter(
                    Q(order=order) | Q(order_id__in=child_ids),
                    method="pending_credit", status="pending",
                ).order_by("order_id").values_list("order_id", "amount"))
                if not options["apply"]:
                    transaction.set_rollback(True)
        except (Order.DoesNotExist, OrderSplitError) as exc:
            raise CommandError(str(exc)) from exc
        mode = "Applied" if options["apply"] else "Dry run (no changes saved)"
        self.stdout.write(f"{mode}: order #{options['order_id']}, repaired children={count}.")
        for order_id, amount in markers:
            self.stdout.write(f"order #{order_id}: pending_credit=${amount:.2f}")
