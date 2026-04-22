# Generated migration for adding identifier field to BillingRecord

from django.db import migrations, models
from django.utils import timezone


def backfill_identifier(apps, schema_editor):
    """
    Backfill identifier field for existing BillingRecord instances.
    Uses format: BILL-{client_id}-{record_id}-{timestamp}
    """
    BillingRecord = apps.get_model('billing', 'BillingRecord')
    
    for record in BillingRecord.objects.all():
        # Create a unique identifier based on client, record id, and date
        timestamp = record.date.strftime('%Y%m%d%H%M%S') if record.date else timezone.now().strftime('%Y%m%d%H%M%S')
        client_id = record.client_id if record.client_id else 'NOCLIENT'
        record.identifier = f'BILL-{client_id}-{record.id}-{timestamp}'
        record.save(update_fields=['identifier'])


def reverse_backfill(apps, schema_editor):
    """
    Reverse migration - no action needed as we're removing the field
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        # Step 1: Add the field as nullable first
        migrations.AddField(
            model_name='billingrecord',
            name='identifier',
            field=models.CharField(max_length=100, null=True, blank=True, verbose_name='Identificador de Factura'),
        ),
        # Step 2: Backfill existing records
        migrations.RunPython(backfill_identifier, reverse_backfill),
        # Step 3: Make the field unique and non-nullable
        migrations.AlterField(
            model_name='billingrecord',
            name='identifier',
            field=models.CharField(max_length=100, unique=True, verbose_name='Identificador de Factura'),
        ),
    ]
