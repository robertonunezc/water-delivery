import os
import logging
from celery import Celery

logger = logging.getLogger(__name__)

"""
Celery configuration for water_delivery project.

This module configures Celery with Mexico timezone and basic settings
for task execution, result backend, and scheduling.
"""

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')

app = Celery('water_delivery')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Celery Configuration Options
app.conf.update(
    # Timezone configuration for Mexico
    timezone='America/Mexico_City',
    enable_utc=True,
    
    # Task configuration
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    
    # Broker configuration
    broker_url=f'redis://:{os.environ.get("REDIS_PASSWORD", "")}@{os.environ.get("REDIS_HOST", "localhost")}:{os.environ.get("REDIS_PORT", "6379")}/0',
    broker_connection_retry_on_startup=True,
    
    # Result backend
    result_backend=f'redis://:{os.environ.get("REDIS_PASSWORD", "")}@{os.environ.get("REDIS_HOST", "localhost")}:{os.environ.get("REDIS_PORT", "6379")}/1',
    result_expires=3600,  # 1 hour
    
    # Task execution
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    
    # Worker configuration
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    
    # Beat scheduler (for periodic tasks)
    beat_scheduler='django_celery_beat.schedulers:DatabaseScheduler',

    # Periodic task schedule
    # Note: Multi-tenant periodic tasks are configured in setup_periodic_tasks()
    # using @app.on_after_configure.connect
    beat_schedule={},
)

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to verify Celery is working correctly."""
    print(f'Request: {self.request!r}')


# =============================================================================
# Multi-Tenant Celery Tasks
# =============================================================================

@app.task(bind=True)
def tenant_task_wrapper(self, schema_name: str, task_path: str, *args, **kwargs):
    """
    Execute a task in a specific tenant's schema context.

    This wrapper ensures that Celery tasks operate within the correct
    tenant schema, maintaining data isolation between tenants.

    Args:
        self: Celery task instance (bound)
        schema_name: PostgreSQL schema name for the tenant
        task_path: Python path to task function (e.g., 'billing.tasks.generate_invoices')
        *args: Positional arguments to pass to the task
        **kwargs: Keyword arguments to pass to the task

    Returns:
        Result from the executed task

    Raises:
        ValueError: If tenant with schema_name not found
        ImportError: If task_path cannot be imported

    Example:
        >>> # Execute billing task for tenant1
        >>> tenant_task_wrapper.delay(
        ...     'tenant1',
        ...     'billing.tasks.generate_invoices',
        ...     client_id=123
        ... )

    Usage in task definition:
        # Instead of calling the task directly:
        # generate_invoices.delay(client_id=123)

        # Call it through the wrapper:
        # tenant_task_wrapper.delay('tenant1', 'billing.tasks.generate_invoices', client_id=123)
    """
    from django_tenants.utils import schema_context, get_tenant_model

    TenantModel = get_tenant_model()

    try:
        tenant = TenantModel.objects.get(schema_name=schema_name)
    except TenantModel.DoesNotExist:
        error_msg = f"Tenant with schema '{schema_name}' not found"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Execute task in tenant's schema context
    with schema_context(schema_name):
        logger.info(
            f"Executing task '{task_path}' for tenant '{tenant.name}' (schema: {schema_name})",
            extra={
                'tenant_id': tenant.id,
                'schema_name': schema_name,
                'task_path': task_path
            }
        )

        # Import and execute task function
        module_name, func_name = task_path.rsplit('.', 1)
        module = __import__(module_name, fromlist=[func_name])
        task_func = getattr(module, func_name)

        return task_func(*args, **kwargs)


@app.task
def run_for_all_tenants(task_path: str, *args, **kwargs):
    """
    Execute a task for all active tenants.

    This function iterates through all tenant schemas (excluding public)
    and queues the specified task for each tenant using tenant_task_wrapper.

    Args:
        task_path: Python path to task function (e.g., 'clients.services.populate_billing_dates')
        *args: Positional arguments to pass to each task
        **kwargs: Keyword arguments to pass to each task

    Returns:
        dict: Summary of queued tasks per tenant

    Example:
        >>> # Run billing date population for all tenants
        >>> run_for_all_tenants.delay('clients.services.populate_billing_dates')

        >>> # Run with arguments
        >>> run_for_all_tenants.delay('orders.tasks.cleanup_old_orders', days=90)
    """
    from django_tenants.utils import get_tenant_model

    TenantModel = get_tenant_model()

    # Get all tenants except public schema
    tenants = TenantModel.objects.exclude(schema_name='public')

    queued_tasks = []
    for tenant in tenants:
        try:
            # Queue task for this tenant
            result = tenant_task_wrapper.delay(
                tenant.schema_name,
                task_path,
                *args,
                **kwargs
            )
            queued_tasks.append({
                'tenant_id': tenant.id,
                'schema_name': tenant.schema_name,
                'task_id': result.id
            })
            logger.info(
                f"Queued task '{task_path}' for tenant '{tenant.name}'",
                extra={
                    'tenant_id': tenant.id,
                    'schema_name': tenant.schema_name,
                    'task_id': result.id
                }
            )
        except Exception as e:
            logger.error(
                f"Failed to queue task '{task_path}' for tenant '{tenant.name}': {str(e)}",
                extra={
                    'tenant_id': tenant.id,
                    'schema_name': tenant.schema_name,
                    'error': str(e)
                },
                exc_info=True
            )

    logger.info(
        f"Queued task '{task_path}' for {len(queued_tasks)}/{tenants.count()} tenants"
    )

    return {
        'task_path': task_path,
        'total_tenants': tenants.count(),
        'queued_tasks': len(queued_tasks),
        'tasks': queued_tasks
    }

