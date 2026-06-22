from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0044_clientcreditconfig_payment_terms'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='client',
            name='requires_note_for_credit',
        ),
    ]
