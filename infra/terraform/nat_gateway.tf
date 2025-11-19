# Create Elastic IP(s) and NAT Gateway(s) for private subnet internet egress

# If nat_per_az=true we will create one NAT per created private subnet AZ, otherwise a single NAT in the first public subnet.
resource "aws_eip" "nat" {
  count  = var.create_private_subnets ? (var.nat_per_az ? var.private_subnets_count : 1) : 0
  domain = "vpc"
  tags = {
    Name = "${var.project_name}-${var.env}-nat-eip-${count.index}"
  }
}

resource "aws_nat_gateway" "nat" {
  count         = var.create_private_subnets ? (var.nat_per_az ? var.private_subnets_count : 1) : 0
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = var.nat_per_az ? var.public_subnet_ids[count.index] : var.public_subnet_ids[0]
  depends_on    = [aws_eip.nat]

  tags = {
    Name = "${var.project_name}-${var.env}-nat-${count.index}"
  }
}

# Route table for private subnets
resource "aws_route_table" "private_rt" {
  count  = var.create_private_subnets ? (var.nat_per_az ? var.private_subnets_count : 1) : 0
  vpc_id = var.vpc_id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = null
    nat_gateway_id = aws_nat_gateway.nat[count.index].id
  }

  tags = {
    Name = "${var.project_name}-${var.env}-private-rt-${count.index}"
  }
}

# Associate private subnets with the route table(s)
resource "aws_route_table_association" "private_assoc" {
  count          = var.create_private_subnets ? var.private_subnets_count : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = var.nat_per_az ? aws_route_table.private_rt[count.index].id : aws_route_table.private_rt[0].id
}

output "nat_gateway_ids" {
  value       = var.create_private_subnets ? aws_nat_gateway.nat[*].id : []
  description = "NAT gateway IDs created (if any)"
}
