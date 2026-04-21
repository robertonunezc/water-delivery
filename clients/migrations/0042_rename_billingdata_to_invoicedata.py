import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0041_alter_address_locality'),
    ]

    operations = [
        # Rename model; db_table stays 'clients_billingdata' (no SQL change)
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
