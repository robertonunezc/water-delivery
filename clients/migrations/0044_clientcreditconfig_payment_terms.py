from django.db import migrations, models


def migrate_existing_payment_terms(apps, schema_editor):
    credit_config = apps.get_model('clients', 'ClientCreditConfig')
    credit_config.objects.filter(client__requires_billing=True).update(
        payment_term_type='invoice_due',
    )


def reverse_existing_payment_terms(apps, schema_editor):
    credit_config = apps.get_model('clients', 'ClientCreditConfig')
    credit_config.objects.update(payment_term_type='monthly_cutoff')


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0043_alter_clientcreditconfig_max_payment_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientcreditconfig',
            name='payment_term_type',
            field=models.CharField(
                choices=[
                    ('monthly_cutoff', 'Fecha de corte mensual'),
                    ('invoice_due', 'Vencimiento posterior a factura'),
                ],
                default='monthly_cutoff',
                max_length=20,
                verbose_name='Modalidad de pago del crédito',
            ),
        ),
        migrations.AddField(
            model_name='clientcreditconfig',
            name='cutoff_day',
            field=models.CharField(
                choices=[
                    ('last_day', 'Último día del mes'),
                    *[(str(day), f'Día {day}') for day in range(1, 32)],
                ],
                default='last_day',
                max_length=10,
                verbose_name='Día de corte mensual',
            ),
        ),
        migrations.RunPython(
            migrate_existing_payment_terms,
            reverse_existing_payment_terms,
        ),
    ]
