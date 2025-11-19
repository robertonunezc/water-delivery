resource "aws_db_subnet_group" "rds_subnets" {
  name       = "${var.project_name}-${var.env}-rds-subnet-group"
  subnet_ids = var.create_private_subnets ? aws_subnet.private[*].id : var.private_subnet_ids

  tags = {
    Name = "${var.project_name}-${var.env}-rds-subnet-group"
  }
}

resource "aws_db_parameter_group" "postgres" {
  name        = "${var.project_name}-${var.env}-postgres-pg"
  family      = "postgres${var.db_engine_version}"
  description = "Custom parameter group for ${var.project_name} ${var.env} (Postgres ${var.db_engine_version})"

  tags = {
    Name = "${var.project_name}-${var.env}-postgres-pg"
  }
}

resource "aws_db_instance" "postgres" {
  identifier              = "${var.project_name}-${var.env}-db"
  allocated_storage      = var.db_allocated_storage
  engine                 = var.db_engine
  engine_version         = var.db_engine_version
  instance_class         = var.db_instance_class
  # 'name' (initial DB name) intentionally omitted to avoid provider restrictions; the DB identifier is set above.
  username               = var.db_username
  # If using Secrets Manager, a random password will be generated and saved there.
  password               = var.use_secrets_manager ? random_password.db_password.result : var.db_password
  db_subnet_group_name   = aws_db_subnet_group.rds_subnets.name
  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  skip_final_snapshot    = true
  publicly_accessible    = false
  multi_az               = false
  backup_retention_period = var.rds_backup_retention
  storage_encrypted       = var.rds_storage_encrypted
  deletion_protection    = var.rds_deletion_protection
  parameter_group_name   = aws_db_parameter_group.postgres.name

  tags = {
    Name = "${var.project_name}-${var.env}-db"
  }
}

# Generate a random password for the DB when using Secrets Manager
resource "random_password" "db_password" {
  length           = 24
  special          = true
}

# Store DB credentials in AWS Secrets Manager (username + password). We store only
# username/password initially. Host/endpoint can be added later if desired.
resource "aws_secretsmanager_secret" "db" {
  count       = var.use_secrets_manager ? 1 : 0
  name        = "${var.project_name}-${var.env}-db-credentials"
  description = "RDS DB credentials for ${var.project_name} (${var.env})"
}

resource "aws_secretsmanager_secret_version" "db_version" {
  count         = var.use_secrets_manager ? 1 : 0
  secret_id     = aws_secretsmanager_secret.db[0].id
  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db_password.result
  })
}
