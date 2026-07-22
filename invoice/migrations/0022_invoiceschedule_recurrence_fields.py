from datetime import date

from django.db import migrations, models


def backfill_invoice_schedule_recurrence_fields(apps, schema_editor):
    InvoiceSchedule = apps.get_model('billing', 'InvoiceSchedule')
    fallback_date = date(2026, 7, 13)

    for schedule in InvoiceSchedule.objects.all().only(
        'id',
        'next_billing_date',
        'created_at',
        'billing_date',
    ):
        start_date = schedule.next_billing_date
        if start_date is None and schedule.created_at:
            start_date = schedule.created_at.date()
        if start_date is None:
            start_date = fallback_date

        InvoiceSchedule.objects.filter(pk=schedule.pk).update(start_date=start_date)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0021_alter_invoice_folio_alter_invoice_identifier_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceschedule',
            name='start_date',
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name='Fecha de Inicio',
            ),
        ),
        migrations.RunPython(
            backfill_invoice_schedule_recurrence_fields,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='invoiceschedule',
            name='start_date',
            field=models.DateField(verbose_name='Fecha de Inicio'),
        ),
    ]
