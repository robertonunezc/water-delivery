# Using existing VPC and subnets: we expect the caller to provide `vpc_id`,
# `public_subnet_ids` and `private_subnet_ids` as variables.

data "aws_vpc" "existing" {
  id = var.vpc_id
}

# Useful: lookup the VPC CIDR for SG rules
output "vpc_cidr_block" {
  value = data.aws_vpc.existing.cidr_block
}
