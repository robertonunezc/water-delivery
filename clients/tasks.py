"""
Celery tasks for the clients app.
"""
from celery import shared_task
from django.core.management import call_command
import logging
from invoice.services import set_billing_date_to_clients
logger = logging.getLogger(__name__)


@shared_task(name='clients.populate_billing_dates')
def populate_billing_dates_task():
    """
    Scheduled task to populate billing dates for all active clients.
    
    This task runs on the first day of each month at 12:00 AM (midnight)
    to update the next_billing_date for all active clients with billing frequency.
    """
    logger.info("Starting populate_billing_dates_task")
    
    try:
        set_billing_date_to_clients()
        logger.info("Successfully completed populate_billing_dates_task")
        return "Billing dates updated successfully"
    except Exception as e:
        logger.error(f"Error in populate_billing_dates_task: {str(e)}")
        raise
