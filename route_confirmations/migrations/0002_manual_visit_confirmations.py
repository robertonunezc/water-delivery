import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


def populate_confirmation_clients(apps, schema_editor):
    visit_confirmation_model = apps.get_model(
        'route_confirmations',
        'VisitConfirmation',
    )
    for confirmation in visit_confirmation_model._base_manager.select_related(
        'route_client',
    ):
        if confirmation.route_client_id and not confirmation.client_id:
            confirmation.client_id = confirmation.route_client.client_id
            confirmation.save(update_fields=['client'])


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0049_credittransaction_date'),
        ('route_confirmations', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='visitconfirmation',
            name='client',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='visit_confirmations',
                to='clients.client',
                verbose_name='Cliente',
            ),
        ),
        migrations.AlterField(
            model_name='visitconfirmation',
            name='route_client',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='visit_confirmations',
                to='routes.routeclient',
                verbose_name='Cliente en ruta',
            ),
        ),
        migrations.RunPython(
            populate_confirmation_clients,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='visitconfirmation',
            name='client',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='visit_confirmations',
                to='clients.client',
                verbose_name='Cliente',
            ),
        ),
        migrations.AddIndex(
            model_name='visitconfirmation',
            index=models.Index(
                fields=['client', 'visit_date'],
                name='route_confirm_client_visit_idx',
            ),
        ),
        migrations.AddConstraint(
            model_name='visitconfirmation',
            constraint=models.UniqueConstraint(
                condition=Q(
                    ('deleted_at__isnull', True),
                    ('route_client__isnull', True),
                ),
                fields=('client', 'visit_date'),
                name='route_confirm_manual_uniq',
            ),
        ),
    ]
