# Address Inline Copy Feature Plan

## Objective
Enable a helper option in the `Client` admin address inline to avoid retyping the same address when creating a second address of the opposite type:

- `shipping` created first, then create `billing` with same data.
- `billing` created first, then create `shipping` with same data.

Label for checkbox:
- **"misma dirección que la anterior"**

## Constraints to Enforce
Show the checkbox only when all conditions below are met:

1. Client has `requires_billing = true`.
2. Current inline address type is `billing` and there is at least one `shipping` address available to copy from.
   - OR current inline address type is `shipping` and there is at least one `billing` address available to copy from.

If conditions are not met, hide the checkbox.

## Current Codebase Findings
- Address type model and validation are already in place:
  - `clients/models.py` -> `Address.type` choices (`billing`, `shipping`, `other`)
  - `Address.clean()` enforces only one `billing` address per client.
- Client admin uses inline addresses:
  - `clients/admin.py` -> `AddressInline`
- Existing admin JS is already OOP-style and compatible with this pattern:
  - `clients/static/clients/admin/*.js`

## Implementation Strategy

### 1) Add a custom inline form field
**Files:**
- `clients/forms.py`
- `clients/admin.py`

**Changes:**
- Create `AddressInlineForm(forms.ModelForm)` with a non-model boolean field:
  - `same_as_previous = forms.BooleanField(required=False, label="misma dirección que la anterior")`
- Attach this form to `AddressInline` in `clients/admin.py`.

### 2) Add admin JS behavior (OOP)
**File:**
- `clients/static/clients/admin/address_inline_copy_previous.js` (new)

**Changes:**
- Implement a class (OOP) that:
  - Detects each address inline row.
  - Reads current row `type` (`billing` or `shipping`).
  - Detects whether client requires billing from `#id_requires_billing`.
  - Finds candidate source row(s) with opposite type.
  - Shows/hides checkbox based on constraints.
  - On checkbox checked, copies fields from selected source row into current row.
  - Keeps copied fields editable.
  - Re-evaluates on:
    - row type change
    - checkbox change
    - `formset:added` event
    - delete checkbox toggle in inline rows

**Fields to copy (proposed):**
- `street`
- `exterior_number`
- `interior_number`
- `locality`
- `municipality`
- `state`
- `zip_code`
- `country`
- `reference`

(Do not copy `type`, `client`, or delete/status management fields.)

### 3) Wire JS into admin media
**File:**
- `clients/admin.py`

**Changes:**
- Add `clients/admin/address_inline_copy_previous.js` to `ClientAdmin.Media.js`.

### 4) Keep backend integrity unchanged
- No model migration required.
- Existing uniqueness rule for billing address remains the source of truth.

## Rule Mapping Matrix

| Current new row type | Opposite existing type needed | `requires_billing` | Show checkbox |
|---|---|---|---|
| `billing` | at least one `shipping` | true | yes |
| `shipping` | at least one `billing` | true | yes |
| any | opposite missing | true | no |
| any | any | false | no |

## Testing Plan

### Automated tests
**File:**
- `clients/tests.py`

**Add tests for:**
- Visibility preconditions in form/admin rendering context (where feasible).
- No impact on existing `Address.clean()` uniqueness behavior for billing.

### Manual QA checklist
1. Open existing client in admin with `requires_billing=true`.
2. Add `shipping` address and save.
3. Add new `billing` row -> checkbox appears.
4. Check checkbox -> address fields auto-populate from shipping.
5. Save and verify billing address created.
6. Reverse flow (`billing` first, then `shipping`) works too.
7. Set `requires_billing=false` -> checkbox hidden.

## PR Strategy (small, reviewable)

### PR 1
- `AddressInlineForm` + admin wiring + JS behavior.
- Target size: ~150–220 LOC.

### PR 2
- Tests + minor UX polish and edge-case fixes.
- Target size: ~80–150 LOC.

## Risks / Edge Cases
- Inline dynamic row indexing (`__prefix__`) and event binding for newly added forms.
- Avoid copying from rows marked for deletion.
- Ensure behavior is limited to address inlines for `ClientAdmin` only.

## Definition of Done
- Checkbox appears only under specified constraints.
- Checkbox copies opposite-type address fields correctly.
- Existing billing uniqueness rule still enforced.
- No regressions in client admin edit flow.
