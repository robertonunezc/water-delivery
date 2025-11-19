output "ecr_repository_url" {
  value       = try(aws_ecr_repository.app[0].repository_url, "")
  description = "ECR repository URL (if created)"
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.main.name
  description = "ECS cluster name"
}

output "alb_dns_name" {
  value       = try(aws_lb.app_alb[0].dns_name, "")
  description = "ALB DNS name (if created)"
}

output "rds_endpoint" {
  value       = aws_db_instance.postgres.address
  description = "RDS endpoint (hostname)"
}

output "db_credentials_secret_arn" {
  value       = var.use_secrets_manager ? aws_secretsmanager_secret.db[0].arn : ""
  description = "ARN of the Secrets Manager secret containing DB credentials (if created)"
}

output "private_subnet_ids" {
  value       = var.create_private_subnets ? aws_subnet.private[*].id : var.private_subnet_ids
  description = "Private subnet IDs that will be used for ECS and RDS"
}

output "private_route_table_ids" {
  value       = var.create_private_subnets ? aws_route_table.private_rt[*].id : []
  description = "Private route table IDs created for private subnets (if any)"
}
