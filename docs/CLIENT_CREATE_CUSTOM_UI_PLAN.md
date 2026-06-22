# Client Create/Edit Custom UI Plan

## Objective

Move client creation and editing away from Django admin into custom templates with a modern UI aligned with the existing client list visual style.

## Current Behavior to Preserve

Source of truth today:

- Admin inline/tab setup and visibility rules in `clients/admin.py`.
- Core business rules in `clients/models.py`.
- Existing update service path in `clients/views.py` (`update_client`) + services.

Functional areas currently handled by admin tabs/inlines:

1. Basic client info
2. Addresses
3. Contacts
4. Invoice frequency (InvoiceSchedule)
5. Invoice data (RFC / razón social / CURP)
6. Credit configuration (ClientCreditConfig)
7. Route assignments (RouteClient)

## UX Direction

Use a two-step experience:

1. Step 1: Basic client data and policy flags (single form)
2. Step 2: Tabbed detail workspace (addresses, contacts, billing, credit config, routes)

This mirrors current admin constraints where related records are meaningful only after the client exists.

### Layout

- Sticky header:
  - Client name/status chip
  - Save actions (Guardar, Guardar y continuar)
  - Validation summary badge
- KPI strip (optional, minimal): active status, billing requirement, available credit, last updated
- Tabs on desktop, accordion fallback on mobile
- Each tab as a dedicated partial template

### Design Rules

- Reuse visual language from `clients/templates/admin/clients/list.html` (cards, rounded surfaces, semantic pills)
- Keep high contrast and compact forms
- Show contextual warnings in place (not hidden in toast only)

## Tab Model and Field Mapping

### Tab: Datos básicos

Primary model: `Client`

Fields:

- name
- active
- external_id
- type
- corporate (only for branch)
- note
- address_link
- can_pay_with_credit
- credit_limit
- requires_billing
- billing_override_enabled (only branch)

Rules:

- If type = branch, corporate is required.
- If type = corporate, corporate must be empty.
- billing_override_enabled only allowed for branch with corporate.
- Respect model clean validations.

### Tab: Direcciones

Primary model: `Address` (formset)

Fields per row:

- type, street, exterior_number, interior_number, locality, municipality, state, zip_code, country, reference, active

Rules:

- At most one billing address per client.
- Preserve legacy `shipping` alias handling in form clean to normalize to `delivery`.
- Optional helper checkbox: duplicate delivery into billing when missing.

### Tab: Contactos

Primary model: `Contact` (formset)

Fields per row:

- name, email, phone, position

### Tab: Facturación

Subsection A: Invoice Data (`InvoiceData`, one-to-one)

- rfc, razon_social, curp

Subsection B: Invoice Frequency (`InvoiceSchedule`, one-to-one)

- frequency, is_active, billing_date, specific_day, weekday, occurrence, notes

Rules:

- Hide entire billing tab when `requires_billing=False`.
- If branch and `billing_override_enabled=False`, show inherited billing info card and disable editing.

### Tab: Crédito

Primary models:

- `Client`: can_pay_with_credit, credit_limit
- `ClientCreditConfig`: max_payment_days, first_notification_days, second_notification_days, overdue_notification_days

Rules:

- Keep model constraints consistent for credit policy.
- If config row does not exist, create on first save.

### Tab: Rutas

Primary model: `RouteClient` (formset)

Fields:

- route, sequence, interval_weeks, anchor_date, is_active, notes

Rules:

- Unique (route, client)
- Keep ordering and due-date behavior untouched.

## Visibility and State Rules (must match admin parity)

When client is new (no PK):

- Show only Datos básicos tab.
- Show instructional banner: save first to enable related tabs.

When editing existing client:

- If `requires_billing=False`: hide/disable billing data + frequency sections.
- If `type=branch` and `billing_override_enabled=False`: billing sections read-only with inheritance notice.
- Otherwise, show all enabled tabs.

## Backend Strategy

### New endpoints (v2)

- `clients:create_v2` GET/POST
- `clients:edit_v2` GET
- `clients:save_section_v2` POST/PATCH (section-based persistence)

Keep old admin and current endpoints active during migration.

### Form architecture

- `ClientCoreForm` (ModelForm)
- `AddressFormSet`
- `ContactFormSet`
- `InvoiceDataForm`
- `InvoiceScheduleForm`
- `ClientCreditConfigForm`
- `RouteClientFormSet`

### Service orchestration

Create an application service in `clients/services/client_ui_service.py`:

- Validates section payloads
- Applies persistence with `transaction.atomic()`
- Triggers side effects currently tied to admin create flow:
  - ensure client product prices on first create
  - optional delivery->billing auto-copy

This keeps business logic out of templates/views.

## Frontend Structure

Template files:

- `clients/templates/clients/client_form_v2.html` (shell)
- `clients/templates/clients/partials/_tab_basic.html`
- `clients/templates/clients/partials/_tab_addresses.html`
- `clients/templates/clients/partials/_tab_contacts.html`
- `clients/templates/clients/partials/_tab_billing.html`
- `clients/templates/clients/partials/_tab_credit.html`
- `clients/templates/clients/partials/_tab_routes.html`

JS (OOP style required):

- `clients/static/clients/js/client-form-manager.js`
  - class `ClientFormManager`
  - tab switching, dirty-state tracking, async section save, validation summary
- Optional modules:
  - class `BillingTabController`
  - class `DynamicFormsetController`

## Validation UX

- Inline field errors + top summary panel
- Persistent warnings for billing completeness
- Do not block save for advisory warnings unless model validation requires blocking

## Rollout Plan

1. Build v2 basic create/edit shell and Datos básicos tab
2. Add Addresses + Contacts tabs with formsets
3. Add Billing tab (invoice data + frequency) with visibility rules
4. Add Credit config tab
5. Add Routes tab
6. Add integration tests and user acceptance pass
7. Switch list page “Nuevo Cliente” button to v2 endpoint

## Testing Plan

Add focused tests for:

1. Create branch without corporate fails
2. Branch with corporate auto-billing inheritance behavior remains intact
3. Billing override visibility and editability
4. One billing address uniqueness
5. Invoice frequency conditional validation
6. Credit config create/update
7. Route assignment uniqueness

## Open Product Questions

1. Single global save vs per-tab save (recommended: per-tab save + final save button)
2. Route tab in phase 1 or phase 2?
3. Draft mode needed?
4. Access policy: admin-only vs permission-based staff users?
