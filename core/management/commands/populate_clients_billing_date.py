"""
Django management command to populate billing dates for all active clients.

Usage:
    python manage.py populate_clients_billing_date
"""

from django.core.management.base import BaseCommand
from clients.services import set_billing_date_to_clients


class Command(BaseCommand):
    help = 'Populate next billing date for all active clients with billing frequency'

    def handle(self, *args, **options):
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Populating Client Billing Dates")
        self.stdout.write("=" * 60 + "\n")

        try:
            set_billing_date_to_clients()
            self.stdout.write(
                self.style.SUCCESS(
                    "\n✓ Successfully updated billing dates for all active clients"
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f"\n✗ Error updating billing dates: {str(e)}"
                )
            )
            raise

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Completed")
        self.stdout.write("=" * 60 + "\n")
