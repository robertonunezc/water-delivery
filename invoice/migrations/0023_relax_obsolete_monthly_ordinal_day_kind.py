from django.db import migrations


RELAX_OBSOLETE_MONTHLY_ORDINAL_COLUMN = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'clients_clientbillingfrecuency'
          AND column_name = 'monthly_ordinal_day_kind'
    ) THEN
        ALTER TABLE clients_clientbillingfrecuency
        ALTER COLUMN monthly_ordinal_day_kind DROP NOT NULL;
    END IF;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0022_invoiceschedule_recurrence_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql=RELAX_OBSOLETE_MONTHLY_ORDINAL_COLUMN,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
