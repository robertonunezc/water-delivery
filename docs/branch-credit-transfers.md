# Branch credit account changes

When enabling a branch's own credit, set its new limit on the basic client form.
All outstanding credit-order debt moves to the branch account and releases the
same amount from corporate. Disabling own credit moves that debt back.

The destination must have capacity for its existing debt plus the transferred
amount. A rejected switch changes neither account nor the branch configuration.
Fully paid orders stay on their historical account. Original sales, payments,
invoices and credit terms remain in history; transfers have paired ledger entries.

## Deployment

Apply the normal tenant schema migrations before running the new application:

```bash
python manage.py migrate_schemas
```

Schema migrations do not transfer existing branch debt. Preview an existing
branch that already uses its own credit but has older corporate-funded orders:

```bash
python manage.py transfer_branch_credit --schema TENANT_SCHEMA --branch-id BRANCH_ID
```

After reviewing the amount, apply the same operation:

```bash
python manage.py transfer_branch_credit --schema TENANT_SCHEMA --branch-id BRANCH_ID --user-id USER_ID --apply
```

Omit `--branch-id` to preview/process all branches with own credit in that tenant.
Every selected branch must pass validation before any selected transfer is
committed. Repeating the command does not transfer the same debt again. Unlinked
account-level debt and unreconciled orders require manual review. The command
uses the original funding account's currently available terms for legacy orders
that have no historical terms snapshot; previously changed terms cannot be
reconstructed from data the application did not retain.
