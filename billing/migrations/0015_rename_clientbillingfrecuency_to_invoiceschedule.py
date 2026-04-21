import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0014_alter_invoice_options_alter_invoiceorderlink_options'),
        ('clients', '0031_alter_client_name_delete_clientbillingfrecuency'),
    ]

    operations = [
        # Rename model; db_table stays 'clients_clientbillingfrecuency' (no SQL change)
        migrations.RenameModel(
            old_name='ClientBillingFrecuency',
            new_name='InvoiceSchedule',
        ),
        # Update related_name and related_query_name (state-only, no SQL)
        migrations.AlterField(
            model_name='invoiceschedule',
            name='client',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='invoice_schedule',
                related_query_name='invoice_schedule',
                to='clients.client',
            ),
        ),
    ]
