terraform {
	required_version = ">= 1.6.0"

	# Step 3 skeleton only:
	# Add required_providers here once you choose your VPS provider
	# (e.g., Hetzner, DigitalOcean, AWS Lightsail, etc.).
}

# -----------------------------
# Inputs (provider-agnostic)
# -----------------------------
variable "project_name" {
	description = "Project name for resource naming and organization"
	type        = string
	default     = "water-delivery"
}

variable "environment" {
	description = "Production environment (e.g., dev, staging, prod)"
	type        = string
	default     = "prod"
}

variable "allowed_ssh_cidrs" {
	description = "CIDRs allowed to reach SSH (port 22)"
	type        = list(string)
	default     = []
}

locals {
	app_name = "${var.project_name}-${var.environment}"
}

# -----------------------------
# Placeholder architecture map
# -----------------------------
# 1) Provider block
#    provider "<your_provider>" { ... }
#
# 2) VPS resource
#    resource "<your_provider>_instance" "vps" { ... }
#
# 3) Firewall / security group
#    - ingress 22 from var.allowed_ssh_cidrs
#    - ingress 80 from 0.0.0.0/0
#    - ingress 443 from 0.0.0.0/0
#    - deny direct public access to app/db ports unless explicitly needed
#
# 4) Import pattern (if VPS already exists)
#    terraform import <your_provider>_instance.vps <existing-instance-id>

output "terraform_skeleton_status" {
	description = "Confirms baseline Terraform skeleton is in place"
	value       = "ready-for-provider-step"
}
