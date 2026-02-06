# Tenant Management Template Usage Guide

Quick start guide for using the tenant management web interface.

## Quick Access

Access the tenant management interface at:
- **Main URL:** `https://yourdomain.com/tenant/list/`
- **Create:** `https://yourdomain.com/tenant/create/`

## Prerequisites

1. User account with staff privileges (`is_staff=True`)
2. Public tenant created (see deployment guide)
3. DNS configured for your domain

---

## Step 1: View All Tenants

Navigate to: `https://yourdomain.com/tenant/list/`

**What you'll see:**
- Dashboard with statistics (total tenants, active, on trial)
- Grid of tenant cards showing:
  - Tenant name and schema
  - Primary domain
  - Status badges (Trial/Paid, Public)
  - Subscription expiry date
  - Action buttons (Edit, Access)

**Actions available:**
- Click "Crear Nuevo Tenant" to add a tenant
- Click "Administrar en Admin" to use Django admin
- Click "Editar" on any tenant card to modify it
- Click "Acceder" to open that tenant's admin panel

---

## Step 2: Create a New Tenant

Navigate to: `https://yourdomain.com/tenant/create/`

### Fill in the form:

#### 1. Tenant Name (required)
```
Example: Agua Cristalina S.A.
```
- Descriptive name with spaces allowed
- This appears in the admin and tenant list

#### 2. Schema Name (required)
```
Example: agua_cristalina
```
- Auto-generated from tenant name (lowercase, underscores)
- Can be manually edited
- Rules:
  - Only lowercase letters, numbers, underscores
  - No spaces or special characters
  - Must be unique across all tenants

#### 3. Domain (required)
```
Example: agua_cristalina.yourdomain.com
```
- Full subdomain where tenant will be accessed
- Must exist in your DNS configuration
- Auto-suggested based on schema name

#### 4. Paid Until (required)
```
Default: One year from today
Example: 2027-02-03
```
- Subscription expiry date
- Use the date picker to select

#### 5. On Trial (optional)
```
☑ Tenant en Período de Prueba
```
- Check if this tenant is in evaluation mode
- Displays "Trial" badge in tenant list

### Submit
Click "Crear Tenant" button

**What happens:**
1. Form is validated (client-side)
2. Submit button shows loading spinner
3. Server creates:
   - PostgreSQL schema with name `agua_cristalina`
   - Tenant database record
   - Domain record linked to tenant
   - Runs all migrations in new schema
4. Success message displayed
5. Redirect to tenant list
6. New tenant appears in the grid

**Time:** Usually 5-30 seconds depending on migration count

---

## Step 3: Access a Tenant

From the tenant list:

1. Find the tenant card you want to access
2. Click the green "Acceder" button
3. Opens in new tab: `https://tenant-domain.com/admin`
4. Login with your credentials
5. You're now in that tenant's isolated admin panel

**Important:** Each tenant has completely isolated data. Changes in one tenant won't affect others.

---

## Common Workflows

### Creating Multiple Tenants

For bulk tenant creation, use the Django shell:

```python
python manage.py shell

from tenant_client.services import create_tenant_with_domain
from datetime import date, timedelta

tenants = [
    ('Agua Pura', 'agua_pura', 'aguapura.yourdomain.com'),
    ('Cristal', 'cristal', 'cristal.yourdomain.com'),
    ('H2O Express', 'h2o_express', 'h2o.yourdomain.com'),
]

for name, schema, domain in tenants:
    tenant, dom = create_tenant_with_domain(
        name=name,
        schema_name=schema,
        domain_name=domain,
        paid_until=date.today() + timedelta(days=365),
        on_trial=True
    )
    print(f"✓ Created: {tenant.name}")
```

### Editing Tenant Details

Two ways to edit:

**Option 1: Django Admin (recommended)**
1. From tenant list, click "Editar" button
2. Opens Django admin change form
3. Edit fields and save
4. Cannot change schema_name after creation

**Option 2: Django Shell**
```python
from tenant_client.models import ClientTenant
from datetime import date, timedelta

tenant = ClientTenant.objects.get(schema_name='agua_cristalina')
tenant.paid_until = date.today() + timedelta(days=365)
tenant.on_trial = False
tenant.save()
```

### Adding Additional Domains

Use the service layer:

```python
from tenant_client.models import ClientTenant
from tenant_client.services import add_domain_to_tenant

tenant = ClientTenant.objects.get(schema_name='agua_cristalina')

# Add custom domain
add_domain_to_tenant(
    tenant=tenant,
    domain_name='custom.aguacristalina.com',
    is_primary=False  # Keep existing primary
)
```

Or via Django Admin:
1. Navigate to Admin → Tenant Client → Domains
2. Click "Add Domain"
3. Select tenant, enter domain
4. Save

### Extending Subscriptions

Use the service layer:

```python
from tenant_client.models import ClientTenant
from tenant_client.services import extend_tenant_subscription

tenant = ClientTenant.objects.get(schema_name='agua_cristalina')

# Extend by 90 days
extend_tenant_subscription(tenant, days=90)

print(f"New expiry: {tenant.paid_until}")
```

---

## UI Features Explained

### Tenant Card Colors
- **Blue header:** Regular tenant
- **Yellow header:** Public schema (special system tenant)
- **Border glow on hover:** Interactive feedback

### Status Badges
- **Prueba (Blue):** Tenant is on trial period
- **Pagado (Green):** Tenant has paid subscription
- **Público (Yellow):** Public schema tenant (system-level)

### Statistics Dashboard
- **Total Tenants:** Count of all tenants in database
- **Activos:** Non-public tenants (business tenants)
- **En Prueba:** Tenants with `on_trial=True`

### Form Auto-Generation
- **Schema Name:** Automatically generated from tenant name
  - "Agua Cristalina" → "agua_cristalina"
  - "H2O Express!" → "h2o_express"
  - Removes accents, spaces, special chars
  - Converts to lowercase

- **Domain Suggestion:** Auto-filled when you tab out of schema field
  - Schema: "agua_cristalina" → Domain: "agua_cristalina.yourdomain.com"

---

## Validation Rules

### Schema Name Validation

**Valid:**
```
agua_cristalina
tenant1
h2o_delivery
company_abc_123
```

**Invalid:**
```
Agua Cristalina    ❌ (uppercase/spaces)
agua-cristalina    ❌ (hyphens not allowed)
agua cristalina    ❌ (spaces)
123tenant          ✓ (but discouraged - start with letter)
public             ❌ (reserved name)
```

### Domain Validation

**Valid:**
```
tenant1.yourdomain.com
subdomain.example.org
custom-domain.com
```

**Invalid (not enforced in form, but won't work):**
```
http://tenant1.com     ❌ (don't include protocol)
tenant1.com:8000       ❌ (don't include port)
localhost              ❌ (use for testing only)
```

---

## Error Messages

### "Schema name must be alphanumeric..."
**Cause:** Invalid characters in schema name
**Fix:** Use only lowercase letters, numbers, underscores

### "Schema name 'public' is a reserved..."
**Cause:** Trying to use a reserved PostgreSQL name
**Fix:** Choose a different schema name

### "Tenant with schema 'X' already exists"
**Cause:** Schema name is already in use
**Fix:** Choose a unique schema name

### "Failed to create tenant: ..."
**Cause:** Various server-side errors
**Fix:** Check application logs at `/app/logs/app.log`

---

## Best Practices

### Naming Conventions

**Schema Names:**
- Use lowercase
- Separate words with underscores
- Keep it short but descriptive
- Use company/client identifier
- Examples: `acme_corp`, `client_123`, `agua_pura`

**Tenant Display Names:**
- Use proper capitalization
- Include legal entity type if relevant
- Examples: "ACME Corporation", "Agua Pura S.A.", "Client #123"

**Domains:**
- Use consistent subdomain pattern
- Match schema name when possible
- Consider using customer-friendly names
- Examples:
  - `acme.yourdomain.com`
  - `client123.yourdomain.com`
  - `custom.clientdomain.com` (for white-label)

### Subscription Management

- Set realistic expiry dates
- Use trials for new customers (30-90 days)
- Automate renewal reminders (future feature)
- Document payment status externally

### DNS Configuration

Before creating a tenant, ensure DNS is configured:

```bash
# Add A record for subdomain
tenant1.yourdomain.com  A  YOUR_VPS_IP

# Or use wildcard (covers all subdomains)
*.yourdomain.com        A  YOUR_VPS_IP
```

Wait 5-15 minutes for DNS propagation before testing.

---

## Keyboard Shortcuts

In the create form:

- **Tab:** Navigate between fields (auto-generates values)
- **Enter:** Submit form (when all fields valid)
- **Esc:** Close error messages

---

## Mobile Usage

The interface is fully responsive:

**On Mobile:**
- Tenant cards stack vertically
- Statistics cards stack
- Forms are touch-friendly
- All features accessible

**Recommended:** Use desktop/laptop for initial tenant creation, mobile for quick status checks.

---

## Troubleshooting

### Can't access tenant list
- Verify you're logged in
- Verify your account has `is_staff=True`
- Check you're on the public domain (not a tenant subdomain)

### Tenant creation hangs
- Check network connection
- Check PostgreSQL is running
- Check application logs for migration errors
- Ensure schema name is unique

### Domain not accessible after creation
- Wait for DNS propagation (5-15 min)
- Verify DNS records with `dig subdomain.yourdomain.com`
- Check nginx is running
- Check SSL certificates are valid

### Wrong data shows in tenant
- Verify you're on correct subdomain
- Check tenant isolation (shouldn't happen)
- Review django-tenants middleware configuration

---

## Testing Checklist

After creating a tenant:

- [ ] Tenant appears in list
- [ ] Can access tenant's admin via link
- [ ] Login works on tenant domain
- [ ] Tenant has empty database (no other tenant's data)
- [ ] Can create clients/orders in tenant
- [ ] Data doesn't appear in other tenants
- [ ] SSL certificate works (HTTPS)
- [ ] Subdomain resolves in browser

---

## Getting Help

**Logs Location:**
- Application: `/app/logs/app.log`
- Gunicorn: `/app/logs/gunicorn-error.log`
- Nginx: `/var/log/nginx/error.log`

**Useful Commands:**
```bash
# View recent logs
docker-compose -f docker-compose.prod.yml logs -f web

# Check tenant schemas in database
docker-compose -f docker-compose.prod.yml exec postgres \
  psql -U wateruser -d water_delivery -c "SELECT schema_name FROM tenant_client_clienttenant;"

# Test DNS resolution
dig tenant1.yourdomain.com

# Test HTTPS connectivity
curl -I https://tenant1.yourdomain.com
```

---

## Related Documentation

- **Full Implementation:** See main deployment plan
- **API Usage:** `tenant_client/services.py` docstrings
- **Template Details:** `tenant_client/TEMPLATES_README.md`
- **django-tenants Docs:** https://django-tenants.readthedocs.io/

---

**Note:** This guide assumes you've completed Phases 1-5 of the implementation plan and have a working Django multi-tenant setup deployed.
