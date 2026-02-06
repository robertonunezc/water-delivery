"""
Views for tenant management.

Provides superuser-only web interface for creating and listing tenants.
All views are integrated with Django admin and require superuser privileges.
"""
from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from datetime import date, timedelta
from .models import ClientTenant, Domain
from .services import create_tenant_with_domain
import logging

logger = logging.getLogger(__name__)


def superuser_required(view_func):
    """
    Decorator that checks if the user is a superuser.
    Redirects to admin login if not authenticated or not a superuser.
    """
    decorated_view = user_passes_test(
        lambda u: u.is_active and u.is_superuser,
        login_url='/admin/login/'
    )(view_func)
    return decorated_view


@superuser_required
def tenant_list(request):
    """
    Display list of all tenants with their domains.

    URL: /admin/tenant-management/
    Method: GET
    Permissions: Superuser only
    """
    tenants = ClientTenant.objects.all().prefetch_related('domains')

    # Prepare tenant data with primary domains
    tenant_data = []
    for tenant in tenants:
        primary_domain = tenant.domains.filter(is_primary=True).first()
        tenant_data.append({
            'tenant': tenant,
            'primary_domain': primary_domain.domain if primary_domain else 'N/A',
            'domain_count': tenant.domains.count()
        })

    context = {
        'tenant_data': tenant_data,
        'total_tenants': tenants.count()
    }

    return render(request, 'tenant_client/tenant_list.html', context)


@superuser_required
def tenant_create(request):
    """
    Create a new tenant with domain.

    URL: /admin/tenant-management/create/
    Methods: GET (show form), POST (process form)
    Permissions: Superuser only

    POST Parameters:
        - name: Tenant display name
        - schema_name: PostgreSQL schema name (alphanumeric + underscore)
        - domain_name: Full domain (e.g., tenant1.yourdomain.com)
        - paid_until: Subscription expiry date (YYYY-MM-DD)
        - on_trial: Boolean, whether tenant is on trial
    """
    if request.method == 'POST':
        try:
            # Extract form data
            name = request.POST.get('name', '').strip()
            schema_name = request.POST.get('schema_name', '').strip()
            domain_name = request.POST.get('domain_name', '').strip()
            paid_until_str = request.POST.get('paid_until', '')
            on_trial = request.POST.get('on_trial') == 'on'

            # Validate required fields
            if not all([name, schema_name, domain_name, paid_until_str]):
                messages.error(request, "All fields are required.")
                return render(request, 'tenant_client/tenant_create.html')

            # Parse date
            try:
                paid_until = date.fromisoformat(paid_until_str)
            except ValueError:
                messages.error(request, "Invalid date format. Use YYYY-MM-DD.")
                return render(request, 'tenant_client/tenant_create.html')

            # Create tenant using service layer
            tenant, domain = create_tenant_with_domain(
                name=name,
                schema_name=schema_name,
                domain_name=domain_name,
                paid_until=paid_until,
                on_trial=on_trial
            )

            messages.success(
                request,
                f"Tenant '{tenant.name}' created successfully! "
                f"Access at: https://{domain.domain}"
            )
            logger.info(
                f"Tenant created via web interface by user {request.user.username}",
                extra={
                    'tenant_id': tenant.id,
                    'schema_name': schema_name,
                    'created_by': request.user.username
                }
            )

            return redirect('tenant_client:list')

        except ValueError as e:
            messages.error(request, f"Validation error: {str(e)}")
            logger.warning(f"Tenant creation validation error: {str(e)}")
        except Exception as e:
            messages.error(request, f"Failed to create tenant: {str(e)}")
            logger.error(f"Tenant creation failed: {str(e)}", exc_info=True)

    # GET request - show form with default values
    context = {
        'default_paid_until': (date.today() + timedelta(days=365)).isoformat()
    }
    return render(request, 'tenant_client/tenant_create.html', context)


@superuser_required
def tenant_detail_api(request, schema_name):
    """
    API endpoint to retrieve tenant details.

    URL: /admin/tenant-management/api/<schema_name>/
    Method: GET
    Permissions: Superuser only
    Returns: JSON
    """
    try:
        tenant = ClientTenant.objects.get(schema_name=schema_name)
        domains = list(tenant.domains.values('domain', 'is_primary'))

        data = {
            'id': tenant.id,
            'name': tenant.name,
            'schema_name': tenant.schema_name,
            'paid_until': tenant.paid_until.isoformat(),
            'on_trial': tenant.on_trial,
            'created_on': tenant.created_on.isoformat(),
            'domains': domains
        }
        return JsonResponse(data)
    except ClientTenant.DoesNotExist:
        return JsonResponse(
            {'error': f"Tenant with schema '{schema_name}' not found"},
            status=404
        )
