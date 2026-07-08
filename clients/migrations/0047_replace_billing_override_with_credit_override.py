from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0046_alter_balancetransaction_transaction_type_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='client',
            name='billing_override_enabled',
        ),
        migrations.AddField(
            model_name='client',
            name='credit_override_enabled',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Si está habilitado, la sucursal podrá usar una configuración '
                    'de crédito propia en lugar de la copiada del corporativo'
                ),
                verbose_name='Usar datos propios de crédito',
            ),
        ),
    ]
