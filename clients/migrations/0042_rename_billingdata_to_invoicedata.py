import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0041_alter_address_locality'),
    ]

    operations = [
        # Explicitly set db_table in migration state so RenameModel skips physical rename
        migrations.AlterModelTable(
            name='billingdata',
            table='clients_billingdata',
        ),
        # Rename model; no SQL generated because db_table is now explicit in migration state
        migrations.RenameModel(
            old_name='BillingData',
            new_name='InvoiceData',
        ),
        # Update related_name / related_query_name (state-only, no SQL)
        migrations.AlterField(
            model_name='invoicedata',
            name='client',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='invoice_data',
                to='clients.client',
            ),
        ),
    ]
