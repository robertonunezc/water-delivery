Terraform scaffold for `water-delivery` infrastructure.

Overview
- Uses an existing VPC. Provide `vpc_id`, `public_subnet_ids`, and `private_subnet_ids`.
- Creates ECR (optional), ECS cluster (Fargate), ALB (optional), and RDS Postgres instance.

Important variables (set via `terraform.tfvars` or CLI):
- `vpc_id` (string) — required
- `public_subnet_ids` (list of strings) — required
- `private_subnet_ids` (list of strings) — required
- `db_password` (sensitive) — avoid committing to git; use CI secrets or Secrets Manager

Secrets manager
- By default this scaffold now generates a random DB password and stores it in AWS Secrets Manager.
- The Terraform variable `use_secrets_manager` controls this behavior (default: true).
- If you prefer to supply a password directly, set `use_secrets_manager = false` and provide `db_password` via a secure mechanism.

Notes & next steps
- This scaffold intentionally does NOT enable a remote state backend. To enable S3 + DynamoDB locking, edit `backend.tf` and provide a state bucket + lock table.
- For production secrets, use AWS Secrets Manager and inject them into ECS task definitions rather than storing plaintext values.
- The GitHub Actions workflows in `.github/workflows/` include a `plan` workflow and a manual `apply` workflow example. Do not run `apply` until you verify variables and credentials.

Quick local usage
```bash
cd infra/terraform
terraform init
terraform plan -var "vpc_id=<your-vpc>" -var "public_subnet_ids=[\"subnet-...\"]" -var "private_subnet_ids=[\"subnet-...\"]" -var "db_password=CHANGE_ME"
# review plan carefully
# terraform apply ...
```

Security reminder
- Do not commit secrets. Use GitHub Secrets and/or AWS Secrets Manager.
