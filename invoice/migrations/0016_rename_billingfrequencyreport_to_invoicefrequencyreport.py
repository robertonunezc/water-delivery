from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0015_rename_clientbillingfrecuency_to_invoiceschedule'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='BillingFrequencyReport',
            new_name='InvoiceFrequencyReport',
        ),
    ]
