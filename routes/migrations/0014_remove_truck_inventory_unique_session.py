from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('routes', '0013_truckinventorysession_truckinventoryline_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='truckinventorysession',
            name='routes_truck_inv_active_uniq',
        ),
    ]
