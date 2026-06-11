from celery.schedules import crontab

INVOICE_SCHEDULES = {
    'populate-billing-dates-all-tenants': {
        'task': 'water_delivery.celery.run_for_all_tenants',
        'schedule': crontab(hour=0, minute=0, day_of_month=1),
        'args': ['invoice.services.set_billing_date_to_clients'],
        'options': {
            'expires': 3600,
        },
    },
}

# Add other app schedules here (e.g. REPORT_SCHEDULES, ORDER_SCHEDULES) as needed

# Merge all schedules into a single dictionary
SCHEDULE = {
    **INVOICE_SCHEDULES,
}
