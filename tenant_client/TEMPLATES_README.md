# Tenant Management Templates

This directory contains the web interface templates for managing multi-tenant operations in the Water Delivery system.

## Templates Overview

### 1. `base_tenant.html`
Base template for all tenant management pages.

**Features:**
- Dark navigation bar with tenant-specific menu
- Responsive Bootstrap 5 layout
- Message notification system
- Custom styling for tenant cards and status badges
- Font Awesome icons throughout

**Extends:** None (base template)

**Blocks:**
- `title` - Page title
- `content` - Main content area
- `extra_css` - Additional CSS
- `extra_js` - Additional JavaScript

---

### 2. `tenant_list.html`
Displays all tenants in the system with their details.

**URL:** `/tenant/list/`
**View:** `tenant_client.views.tenant_list`
**Permission:** Staff members only

**Features:**
- Statistics dashboard (total tenants, active, on trial)
- Responsive card grid layout
- Color-coded tenant cards
  - Yellow border for public schema
  - Primary blue for regular tenants
- Status badges (Trial/Paid, Public)
- Direct links to tenant admin panels
- One-click access to each tenant's domain

**Context Variables:**
- `tenant_data` - List of dicts with `tenant`, `primary_domain`, `domain_count`
- `total_tenants` - Total count of all tenants

**Card Information Displayed:**
- Tenant name
- Schema name
- Primary domain (clickable)
- Domain count
- Trial/Paid status
- Public schema indicator
- Subscription expiry date
- Creation date
- Edit and access buttons

---

### 3. `tenant_create.html`
Form for creating new tenants with domains.

**URL:** `/tenant/create/`
**View:** `tenant_client.views.tenant_create`
**Permission:** Staff members only

**Features:**
- Guided form with helpful tooltips
- Real-time schema name validation
- Auto-generation of schema name from tenant name
- Domain suggestion based on current hostname
- Client-side validation before submission
- Loading state on form submission
- Date picker for subscription expiry (defaults to 1 year)
- Trial status toggle

**Form Fields:**

1. **Tenant Name** (required)
   - Display name for the tenant
   - Can contain spaces and special characters
   - Auto-generates schema_name in lowercase/underscore format

2. **Schema Name** (required)
   - PostgreSQL schema identifier
   - Pattern: `[a-z0-9_]+` (lowercase alphanumeric + underscores only)
   - Must be unique
   - Auto-generated from tenant name (editable)

3. **Domain** (required)
   - Full domain where tenant will be accessible
   - Format: `tenant1.yourdomain.com`
   - Must be configured in DNS

4. **Paid Until** (required)
   - Subscription expiry date
   - Defaults to 1 year from today
   - Date picker input

5. **On Trial** (optional)
   - Checkbox to mark tenant as trial
   - Default: unchecked

**JavaScript Features:**
- Auto-generates `schema_name` from `name` input
- Validates schema_name pattern (lowercase, numbers, underscores only)
- Suggests domain based on schema_name
- Disables submit button if validation fails
- Shows loading spinner during submission

**Validation:**
- Client-side: Pattern matching for schema_name
- Server-side: Handled in `tenant_client.services.create_tenant_with_domain()`
- Prevents reserved schema names (public, pg_catalog, etc.)

---

## URL Configuration

The templates rely on the following URL patterns (defined in `tenant_client/urls.py`):

```python
urlpatterns = [
    path('list/', views.tenant_list, name='list'),           # List all tenants
    path('create/', views.tenant_create, name='create'),     # Create new tenant
]
```

**URL Namespace:** `tenant_client`

**Full URLs:**
- List: `https://yourdomain.com/tenant/list/`
- Create: `https://yourdomain.com/tenant/create/`

---

## Styling

### Color Scheme
- **Primary:** Purple gradient (`#667eea` to `#764ba2`)
- **Success:** Green (`#28a745`) - Paid tenants
- **Info:** Blue (`#17a2b8`) - Trial tenants
- **Warning:** Yellow (`#ffc107`) - Public schema
- **Danger:** Red (`#dc3545`) - Expired subscriptions

### Custom CSS Classes
- `.tenant-card` - Tenant card with hover effect
- `.stat-card` - Statistics card with gradient background
- `.tenant-header` - Page header with gradient background
- `.badge-trial` - Badge for trial tenants
- `.badge-paid` - Badge for paid tenants
- `.badge-expired` - Badge for expired subscriptions

---

## Access Control

All tenant management views require:
- User must be authenticated
- User must have `is_staff = True`

Enforced via `@staff_member_required` decorator in views.

---

## Navigation

The tenant management interface is accessible from:

1. **Public Domain Admin Panel**
   - URL: `https://yourdomain.com/admin`
   - Navigate to "Tenant Client" section

2. **Direct URLs**
   - List: `https://yourdomain.com/tenant/list/`
   - Create: `https://yourdomain.com/tenant/create/`

3. **Navigation Bar**
   - Visible when logged in as staff
   - Links to List, Create, and Admin

---

## Integration with Django Admin

The templates complement the Django admin interface:

- **Admin Integration:** Links to edit tenants in Django admin
- **Domain Management:** Domains must be added via admin after tenant creation (or use the service layer)
- **Advanced Operations:** Use Django admin for complex operations

**Admin URLs Referenced:**
- `admin:tenant_client_clienttenant_changelist` - Tenant list in admin
- `admin:tenant_client_clienttenant_change` - Edit tenant in admin
- `admin:index` - Django admin home

---

## Workflow Example

### Creating a New Tenant

1. Navigate to `https://yourdomain.com/tenant/create/`
2. Fill in tenant details:
   - Name: "Agua Cristalina"
   - Schema: `agua_cristalina` (auto-generated)
   - Domain: `agua_cristalina.yourdomain.com`
   - Paid Until: 2027-02-03
   - On Trial: Checked
3. Click "Crear Tenant"
4. System creates:
   - PostgreSQL schema `agua_cristalina`
   - Tenant record in database
   - Domain record linked to tenant
   - All migrations run in new schema
5. Redirects to tenant list with success message
6. Tenant card appears in list
7. Click "Acceder" to visit tenant's admin panel

---

## Error Handling

### Client-Side Validation Errors
- Schema name pattern mismatch: Shows error message below input
- Empty required fields: HTML5 validation prevents submission

### Server-Side Validation Errors
- Displayed via Django messages framework
- Error types:
  - Invalid schema name characters
  - Reserved schema name (public, pg_catalog, etc.)
  - Duplicate schema name
  - Duplicate domain name
  - Invalid date format

### Network/Database Errors
- Caught by try/except in views
- User-friendly error messages displayed
- Full error logged to application logs

---

## Responsive Design

All templates are fully responsive:

- **Mobile (< 768px):** Single column layout, stacked cards
- **Tablet (768px - 992px):** 2 columns for tenant cards
- **Desktop (> 992px):** 3 columns for tenant cards

Bootstrap 5 breakpoints:
- `col-md-6` - 2 columns on medium devices
- `col-lg-4` - 3 columns on large devices

---

## Browser Compatibility

Tested and compatible with:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

**Dependencies:**
- Bootstrap 5.3.0 (CDN)
- Font Awesome 6.0.0 (CDN)
- Modern JavaScript (ES6+)

---

## Customization

### Changing Colors
Edit the `<style>` block in `base_tenant.html`:

```css
.stat-card {
    background: linear-gradient(135deg, #YOUR_COLOR1, #YOUR_COLOR2);
}
```

### Adding New Fields to Create Form
1. Add input field to `tenant_create.html`
2. Update `tenant_client/views.tenant_create` to extract field
3. Update `tenant_client/services.create_tenant_with_domain()` signature

### Customizing Tenant Cards
Edit the card structure in `tenant_list.html`:

```html
<div class="card tenant-card">
    <!-- Add your custom content here -->
</div>
```

---

## Security Considerations

1. **CSRF Protection:** All forms include `{% csrf_token %}`
2. **XSS Prevention:** User input is escaped by Django templates
3. **Permission Checks:** `@staff_member_required` on all views
4. **SQL Injection:** Service layer uses ORM (no raw SQL)
5. **Domain Validation:** Regex pattern enforced on schema names

---

## Future Enhancements

Potential improvements for the tenant management interface:

- [ ] Inline domain editing (add/remove domains without admin)
- [ ] Tenant usage statistics (storage, users, orders)
- [ ] Bulk tenant operations (suspend, extend subscription)
- [ ] Tenant search and filtering
- [ ] Export tenant list to CSV
- [ ] Tenant deletion with confirmation workflow
- [ ] Subscription renewal reminders
- [ ] Tenant activity logs
- [ ] Domain DNS verification check
- [ ] Automated tenant provisioning API

---

## Troubleshooting

### "Template does not exist" error
**Cause:** Django can't find the template
**Solution:** Ensure `tenant_client` is in `INSTALLED_APPS` in settings.py

### Tenant list shows no tenants
**Cause:** No tenants in database or permission issue
**Solution:**
1. Create public tenant first (see Phase 7 of implementation plan)
2. Verify user has `is_staff=True`

### Create form submission fails silently
**Cause:** JavaScript or validation error
**Solution:**
1. Check browser console for JavaScript errors
2. Verify CSRF token is present
3. Check server logs for Python exceptions

### Styling not loading
**Cause:** CDN blocked or no internet
**Solution:**
1. Check network tab in browser dev tools
2. Consider hosting Bootstrap/Font Awesome locally

---

## Related Files

- **Views:** `tenant_client/views.py`
- **Services:** `tenant_client/services.py`
- **Models:** `tenant_client/models.py`
- **Admin:** `tenant_client/admin.py`
- **URLs:** `tenant_client/urls.py`
- **Tests:** `tenant_client/test_utils.py`

---

## Support

For issues or questions:
1. Check application logs: `/app/logs/app.log`
2. Review Django debug output (if DEBUG=True)
3. Verify tenant model in Django admin
4. Check PostgreSQL schema: `\dn` in psql

---

## License

Part of the Water Delivery Multi-Tenant System.
Powered by django-tenants 3.9.0.
