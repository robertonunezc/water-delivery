# Tenant Management Security

## Access Control Overview

The tenant management system implements strict access controls to ensure only authorized superusers can create and manage tenants.

## Permission Levels

### Superuser (Required)
All tenant management operations require **superuser privileges** (`is_superuser=True`).

**Can Access:**
- Tenant management dashboard (`/admin/tenant-management/`)
- Tenant creation form (`/admin/tenant-management/create/`)
- Tenant API endpoints
- Django admin tenant models
- All Django admin features

**Cannot Access (without superuser):**
- Regular staff users (`is_staff=True` but `is_superuser=False`) are **blocked**
- Non-authenticated users are redirected to `/admin/login/`
- Tenant users (on subdomains) cannot access public schema tenant management

### Staff User (Insufficient)
Staff members **without** superuser status have:
- Access to Django admin interface
- Ability to manage models they have permissions for
- **NO access** to tenant management

### Regular User (No Access)
Regular users have no access to any administrative features.

---

## URL Structure

All tenant management URLs are under the `/admin/` path for security:

```
https://yourdomain.com/admin/                          # Django admin home
https://yourdomain.com/admin/tenant-management/        # Tenant list (superuser only)
https://yourdomain.com/admin/tenant-management/create/ # Create tenant (superuser only)
```

**Previous insecure URLs (now removed):**
```
❌ /tenant/list/    # Was accessible to any staff member
❌ /tenant/create/  # Was accessible to any staff member
```

---

## Decorator Implementation

### Custom `@superuser_required` Decorator

```python
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
```

**Checks:**
1. User is authenticated
2. User is active (`is_active=True`)
3. User has superuser privileges (`is_superuser=True`)

**On Failure:**
- Redirects to `/admin/login/`
- After login, redirects back to original URL (if authorized)

### Applied to Views

```python
@superuser_required
def tenant_list(request):
    # View tenant list
    pass

@superuser_required
def tenant_create(request):
    # Create new tenant
    pass

@superuser_required
def tenant_detail_api(request, schema_name):
    # API endpoint for tenant details
    pass
```

---

## Template Security

### Conditional Rendering

Templates only show tenant management links to superusers:

```django
{% if user.is_authenticated and user.is_superuser %}
    <li class="nav-item">
        <a href="{% url 'tenant_client:list' %}">Gestión de Tenants</a>
    </li>
{% endif %}
```

### Admin Integration

The Django admin index page shows the "Multi-Tenant Management" section only to superusers:

```django
{% if user.is_superuser %}
    <div class="module">
        <caption>Multi-Tenant Management</caption>
        <!-- Tenant management links -->
    </div>
{% endif %}
```

---

## Schema Isolation

### Public vs Tenant Schemas

**Public Schema** (`yourdomain.com`):
- Contains tenant management tables
- Only accessible to superusers
- Hosts Django admin interface
- No business data (clients, orders, etc.)

**Tenant Schemas** (`tenant1.yourdomain.com`):
- Isolated PostgreSQL schemas
- Contains business data
- Staff users can manage tenant-specific data
- Cannot access public schema or other tenants

### Middleware Protection

`django-tenants` middleware (`TenantMainMiddleware`) ensures:
- Requests are routed to correct schema based on domain
- Cross-tenant data access is impossible
- Schema switching requires explicit code

---

## Best Practices

### Creating Superusers

Only create superuser accounts for trusted administrators:

```bash
docker-compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

**Guidelines:**
- Use strong passwords (20+ characters, mixed case, symbols)
- Enable 2FA if available (Django add-on)
- Limit number of superuser accounts (1-3 maximum)
- Use personal accounts (no shared credentials)
- Rotate passwords quarterly

### Granting Tenant Access

For tenant-specific operations, create staff users in each tenant:

```python
# In tenant schema context
from django.contrib.auth.models import User

user = User.objects.create_user(
    username='tenant_admin',
    email='admin@tenant.com',
    password='secure_password',
    is_staff=True,
    is_superuser=False  # Never make tenant users superusers
)
```

**Tenant staff users can:**
- Access that tenant's admin panel
- Manage clients, orders, billing for that tenant
- **Cannot:** Create tenants, access other tenants, manage infrastructure

---

## Audit Logging

All tenant management operations are logged:

```python
logger.info(
    f"Created tenant '{name}' with schema '{schema_name}'",
    extra={
        'tenant_id': tenant.id,
        'schema_name': schema_name,
        'created_by': request.user.username,
        'action': 'tenant_create'
    }
)
```

**Logged Events:**
- Tenant creation
- Tenant modification
- Domain additions
- Subscription extensions
- Failed access attempts

**Log Location:** `/app/logs/app.log` (JSON format)

---

## Attack Vectors & Mitigations

### 1. Privilege Escalation
**Risk:** Staff user attempts to access tenant management
**Mitigation:** `@superuser_required` decorator blocks access

### 2. Cross-Tenant Access
**Risk:** Tenant user tries to access another tenant's data
**Mitigation:** `django-tenants` middleware enforces schema isolation

### 3. SQL Injection
**Risk:** Malicious schema names or SQL in inputs
**Mitigation:**
- Schema name validation (alphanumeric + underscore only)
- Django ORM (no raw SQL)
- Reserved name blacklist

### 4. CSRF Attacks
**Risk:** Unauthorized tenant creation via forged requests
**Mitigation:**
- `{% csrf_token %}` in all forms
- Django CSRF middleware enabled
- `CSRF_TRUSTED_ORIGINS` configured

### 5. XSS Attacks
**Risk:** Malicious scripts in tenant names or domains
**Mitigation:**
- Django template auto-escaping
- Input validation on schema names
- Content Security Policy headers (nginx)

### 6. Brute Force
**Risk:** Repeated login attempts to admin
**Mitigation:**
- Rate limiting (Django Ratelimit recommended)
- Strong password requirements
- Account lockout after failed attempts (Django Defender)

---

## Security Checklist

### Deployment
- [ ] All superuser accounts have strong passwords
- [ ] `DEBUG=False` in production
- [ ] `SECRET_KEY` is unique and secure
- [ ] `ALLOWED_HOSTS` properly configured
- [ ] SSL certificates installed and valid
- [ ] HSTS headers enabled
- [ ] Firewall rules configured (block direct PostgreSQL access)

### User Management
- [ ] Superuser accounts limited to 1-3
- [ ] No shared superuser accounts
- [ ] Tenant staff users have `is_superuser=False`
- [ ] Regular password rotation policy
- [ ] Disabled accounts removed

### Monitoring
- [ ] Log aggregation configured (Grafana/Loki)
- [ ] Alerts for failed superuser login attempts
- [ ] Alerts for new tenant creation
- [ ] Regular security audits
- [ ] Backup verification

---

## Compliance

### Data Isolation
Each tenant's data is completely isolated:
- Separate PostgreSQL schemas
- No cross-tenant queries possible
- Schema names are non-guessable

### GDPR/Privacy
- Tenant data can be deleted by dropping schema
- Export functionality for data portability
- No shared user databases between tenants

### Access Control
- Role-based access (superuser vs staff vs regular)
- Principle of least privilege
- Separation of duties (tenant admin ≠ infrastructure admin)

---

## Testing Security

### Verify Superuser Requirement

```bash
# Create a staff user (non-superuser)
docker-compose exec web python manage.py shell

from django.contrib.auth.models import User
staff_user = User.objects.create_user(
    username='staff_test',
    password='password',
    is_staff=True,
    is_superuser=False
)

# Try to access tenant management
# Should redirect to admin login
curl -L -c cookies.txt -b cookies.txt \
  -u staff_test:password \
  https://yourdomain.com/admin/tenant-management/

# Expected: 403 Forbidden or redirect
```

### Verify Schema Isolation

```python
# In tenant1 schema
from clients.models import Client
client = Client.objects.create(name='Tenant 1 Client')

# Switch to tenant2 schema
from django_tenants.utils import schema_context

with schema_context('tenant2'):
    # Should return 0 (data isolated)
    count = Client.objects.count()
    assert count == 0, "Cross-tenant data leak detected!"
```

---

## Incident Response

### Unauthorized Access Attempt
1. Check logs for source IP and user
2. Lock compromised account immediately
3. Rotate affected passwords
4. Review recent tenant creation activity
5. Audit all tenant schemas for unauthorized changes

### Compromised Superuser Account
1. **Immediately** disable account
2. Create new superuser account
3. Review all tenants created by compromised account
4. Check for backdoor accounts in tenant schemas
5. Rotate all secrets (SECRET_KEY, database passwords)
6. Review nginx/gunicorn access logs
7. Consider database restore if data integrity questioned

---

## Future Enhancements

Security improvements to consider:

- [ ] Two-factor authentication for superusers
- [ ] IP whitelist for admin access
- [ ] Session timeout for superuser sessions
- [ ] Tenant creation approval workflow
- [ ] Automated security scanning (Bandit, Safety)
- [ ] Penetration testing
- [ ] Bug bounty program

---

## References

- Django Security: https://docs.djangoproject.com/en/5.2/topics/security/
- django-tenants Security: https://django-tenants.readthedocs.io/en/latest/
- OWASP Top 10: https://owasp.org/www-project-top-ten/
- PostgreSQL Schema Security: https://www.postgresql.org/docs/current/ddl-schemas.html

---

**Last Updated:** 2026-02-03
**Security Contact:** admin@yourdomain.com
