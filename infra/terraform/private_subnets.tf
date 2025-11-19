# Create private subnets in the existing VPC (one per AZ). These are used for ECS tasks and RDS.

data "aws_availability_zones" "available" {}

resource "aws_subnet" "private" {
  count                   = var.create_private_subnets ? var.private_subnets_count : 0
  vpc_id                  = var.vpc_id
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  cidr_block              = length(var.private_subnet_cidrs) > count.index ? var.private_subnet_cidrs[count.index] : cidrsubnet(data.aws_vpc.existing.cidr_block, 8, count.index + 10)
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.project_name}-${var.env}-private-${count.index}"
  }
}

output "created_private_subnet_ids" {
  value       = var.create_private_subnets ? aws_subnet.private[*].id : []
  description = "List of private subnet IDs created by Terraform (if enabled)"
}
