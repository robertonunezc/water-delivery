# Generated manually for cantidad_cobrada field addition
# This migration adds the cantidad_cobrada field to the Order model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0007_alter_order_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='cantidad_cobrada',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Cantidad realmente cobrada al cliente (puede ser mayor al total para agregar saldo)', max_digits=10, null=True, verbose_name='Cantidad Cobrada'),
        ),
    ]