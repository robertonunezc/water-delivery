# Generated manually for billing domain rename: BillingRecord→Invoice, BillingOrder→InvoiceOrderLink
# Preserves existing DB table names (billing_billingrecord, billing_billingorder)
# and the FK column name (billing_record_id) to avoid destructive SQL.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0012_billingrecord_created_at_billingrecord_deleted_at_and_more'),
        ('clients', '0001_initial'),
        ('orders', '0001_initial'),
    ]

    operations = [
        # Lock current table names explicitly in the migration state so that
        # the subsequent RenameModel operations do NOT rename the DB tables.
        migrations.AlterModelTable(
            name='BillingRecord',
            table='billing_billingrecord',
        ),
        migrations.AlterModelTable(
            name='BillingOrder',
            table='billing_billingorder',
        ),

        # Rename models (Python-level only; tables stay the same due to db_table above)
        migrations.RenameModel(
            old_name='BillingRecord',
            new_name='Invoice',
        ),
        migrations.RenameModel(
            old_name='BillingOrder',
            new_name='InvoiceOrderLink',
        ),

        # Rename the FK field on InvoiceOrderLink (was billing_record → invoice).
        # This renames the DB column from billing_record_id to invoice_id.
        # We then immediately add db_column='billing_record_id' via AlterField to
        # restore the original column name and avoid touching production data.
        migrations.RenameField(
            model_name='invoiceorderlink',
            old_name='billing_record',
            new_name='invoice',
        ),
        migrations.AlterField(
            model_name='invoiceorderlink',
            name='invoice',
            field=models.ForeignKey(
                db_column='billing_record_id',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='invoice_links',
                to='billing.invoice',
                verbose_name='Factura',
            ),
        ),

        # Update related_name on the order FK (state-only, no SQL)
        migrations.AlterField(
            model_name='invoiceorderlink',
            name='order',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='invoice_links',
                to='orders.order',
                verbose_name='Venta',
            ),
        ),

        # Update related_name on the client FK of Invoice (state-only, no SQL)
        migrations.AlterField(
            model_name='invoice',
            name='client',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='invoices',
                to='clients.client',
                verbose_name='Cliente',
            ),
        ),
    ]
