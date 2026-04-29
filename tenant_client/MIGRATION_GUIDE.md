# Security Update Migration Guide

## Overview

The tenant management interface has been secured with superuser-only access controls. All URLs have been moved under the `/admin/` path.

## What Changed

### URL Changes

**Before (Insecure):**
```
/tenant/list/      → Any staff member could access
/tenant/create/    → Any staff member could create tenants
```

**After (Secure):**
```
/admin/tenant-management/         → Superuser only
/admin/tenant-management/create/  → Superuser only
```

### Permission Changes

**Before:**
- Required: `@staff_member_required` (`is_staff=True`)
- Staff users could manage tenants

**After:**
- Required: `@superuser_required` (`is_superuser=True`)
- Only superusers can manage tenants

### Access Points

**New Admin Integration:**
- Django admin homepage shows "Multi-Tenant Management" section (superusers only)
- Click "Tenant Management Dashboard" to access tenant list
- Click "Create Tenant" to create new tenants

---

## Migration Steps

### 1. Update Bookmarks/Documentation

If you have **bookmarked** URLs, update them:

```
OLD: https://yourdomain.com/tenant/list/
NEW: https://yourdomain.com/admin/tenant-management/

OLD: https://yourdomain.com/tenant/create/
NEW: https://yourdomain.com/admin/tenant-management/create/
```

### 2. Review User Permissions

Check which users had staff access but should not be superusers:

```python
python manage.py shell

from django.contrib.auth.models import User

# List all staff users
staff_users = User.objects.filter(is_staff=True, is_superuser=False)
for user in staff_users:
    print(f"{user.username}: is_staff={user.is_staff}, is_superuser={user.is_superuser}")

# These users will NO LONGER have access to tenant management
```

### 3. Grant Superuser Access (If Needed)

If certain staff users need tenant management access:

```python
from django.contrib.auth.models import User

user = User.objects.get(username='trusted_admin')
user.is_superuser = True
user.save()

print(f"✓ {user.username} is now a superuser")
```

**Warning:** Only grant superuser to trusted administrators. Superusers have full system access.

### 4. Update Custom Scripts

If you have scripts that call tenant management URLs, update them:

**Before:**
```python
import requests

response = requests.post(
    'https://yourdomain.com/tenant/create/',
    data={...},
    auth=('staff_user', 'password')
)
```

**After:**
```python
import requests

response = requests.post(
    'https://yourdomain.com/admin/tenant-management/create/',
    data={...},
    auth=('superuser', 'password')  # Must be superuser
)
```

### 5. Update CI/CD Pipelines

If your deployment scripts create tenants:

```bash
# OLD (won't work anymore)
curl -u staff_user:password https://yourdomain.com/tenant/create/

# NEW
curl -u superuser:password https://yourdomain.com/admin/tenant-management/create/
```

---

## Testing the Migration

### 1. Verify Superuser Access

```bash
# Login as superuser
open https://yourdomain.com/admin/

# Navigate to tenant management
# Should see "Multi-Tenant Management" section on admin home page
# Click "Tenant Management Dashboard"
# Should load successfully
```

### 2. Verify Staff User Blocked

```bash
# Login as staff user (non-superuser)
open https://yourdomain.com/admin/

# Try to access tenant management directly
open https://yourdomain.com/admin/tenant-management/

# Expected: Redirected to login or shown 403 error
```

### 3. Verify Old URLs Removed

```bash
# Try old URLs
curl -I https://yourdomain.com/tenant/list/

# Expected: 404 Not Found
```

---

## Breaking Changes

### For Staff Users
- Staff users without superuser privileges can no longer:
  - View tenant list
  - Create new tenants
  - Access tenant management interface

**Migration:** Grant superuser status or use Django admin to manage ClientTenant model directly

### For API Integrations
- All API endpoints moved under `/admin/` path
- Authentication now requires superuser credentials
- Update API clients to use new URLs

### For Scripts
- Tenant creation scripts need superuser credentials
- Update URLs in automation scripts
- Update service layer imports (no changes, still works)

---

## Rollback Plan

If you need to rollback to staff-only access:

### 1. Revert Decorator

Edit `tenant_client/views.py`:

```python
# Change from:
@superuser_required
def tenant_list(request):
    ...

# Back to:
@staff_member_required
def tenant_list(request):
    ...
```

### 2. Revert URLs

Edit `water_delivery/public_urls.py`:

```python
# Change from:
path('admin/tenant-management/', include('tenant_client.urls')),

# Back to:
path('tenant/', include('tenant_client.urls')),
```

### 3. Restart Services

```bash
docker-compose -f docker-compose.prod.yml restart web
```

---

## Security Benefits

This migration provides:

1. **Principle of Least Privilege**
   - Tenant creation is infrastructure-level operation
   - Should only be accessible to system administrators

2. **Reduced Attack Surface**
   - Fewer users with tenant creation privileges
   - Harder for compromised staff accounts to create rogue tenants

3. **Better Compliance**
   - Clear separation between tenant admins and infrastructure admins
   - Audit trail for superuser actions

4. **Centralized Access**
   - All admin operations under `/admin/` path
   - Consistent authentication mechanism
   - Single point of access control

---

## FAQ

**Q: Can staff users still manage tenants via Django admin?**
A: No. The ClientTenant model in Django admin also requires superuser privileges due to `TenantAdminMixin`.

**Q: What if I need to give someone tenant creation access but not full superuser?**
A: Consider creating a custom Django permission and updating the decorator:
```python
@user_passes_test(lambda u: u.has_perm('tenant_client.add_clienttenant'))
```

**Q: Will tenant staff users be affected?**
A: No. Tenant users (on subdomains) are unaffected. They manage their tenant's data, not infrastructure.

**Q: Can I create tenants programmatically without superuser?**
A: Yes, use the service layer in Python code:
```python
from tenant_client.services import create_tenant_with_domain
# No HTTP authentication required when run as management command or script
```

**Q: What happens if a staff user tries to access the old URLs?**
A: They'll get a 404 error. Old URLs are completely removed.

---

## Support

If you encounter issues during migration:

1. Check application logs: `/app/logs/app.log`
2. Verify user permissions: `python manage.py shell` → check `user.is_superuser`
3. Test with curl: `curl -u username:password https://yourdomain.com/admin/tenant-management/`
4. Review SECURITY.md for access control details

---

**Migration completed:** 2026-02-03
