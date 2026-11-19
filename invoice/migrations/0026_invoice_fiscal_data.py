from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0025_add_invoice_draft_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice', name='rfc',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='RFC'),
        ),
        migrations.AddField(
            model_name='invoice', name='razon_social',
            field=models.TextField(blank=True, default='', verbose_name='Razón social'),
        ),
        migrations.AddField(
            model_name='invoice', name='curp',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='CURP'),
        ),
        migrations.AddField(
            model_name='invoice', name='billing_address',
            field=models.TextField(blank=True, default='', verbose_name='Domicilio fiscal'),
        ),
    ]
