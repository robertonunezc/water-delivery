variable "project_name" {
  description = "Project name used as prefix for resources"
  type        = string
  default     = "water-delivery"
}

variable "env" {
  description = "Environment name (prod/staging/dev)"
  type        = string
  default     = "prod"
}

variable "vpc_id" {
  description = "ID of the existing VPC to use (required). Example: vpc-0abc123..."
  type        = string
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs (for ALB) in the VPC. Example: [\"subnet-...\", \"subnet-...\"]"
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs (for ECS tasks and RDS) in the VPC. Example: [\"subnet-...\", \"subnet-...\"]"
  type        = list(string)
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "waterdelivery"
}

variable "db_username" {
  description = "Database admin username"
  type        = string
  default     = "wateruser"
}

variable "db_password" {
  description = "Database password (sensitive). For production, use Secrets Manager; do NOT commit plaintext values."
  type        = string
  sensitive   = true
  default     = ""
}

variable "use_secrets_manager" {
  description = "When true, Terraform will generate a random DB password and store it in AWS Secrets Manager."
  type        = bool
  default     = true
}

variable "create_private_subnets" {
  description = "When true, Terraform will create private subnets in the existing VPC (one per AZ by default)."
  type        = bool
  default     = true
}

variable "private_subnets_count" {
  description = "Number of private subnets to create (one per AZ)."
  type        = number
  default     = 3
}

variable "nat_per_az" {
  description = "Whether to create a NAT gateway per AZ. If false, create a single NAT in the first public subnet."
  type        = bool
  default     = false
}

variable "rds_storage_encrypted" {
  description = "Whether to enable encryption at rest for RDS (uses AWS-managed KMS key if true)."
  type        = bool
  default     = false
}

variable "rds_deletion_protection" {
  description = "Prevent accidental deletion of the RDS instance when true."
  type        = bool
  default     = false
}

variable "rds_backup_retention" {
  description = "Number of days to retain automated backups for RDS"
  type        = number
  default     = 7
}

variable "private_subnet_cidrs" {
  description = "Optional explicit CIDR blocks for private subnets. If provided, the list length must be >= private_subnets_count."
  type        = list(string)
  default     = ["10.0.100.0/24", "10.0.101.0/24", "10.0.102.0/24"]
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB for RDS"
  type        = number
  default     = 20
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_engine" {
  description = "RDS engine"
  type        = string
  default     = "postgres"
}

variable "db_engine_version" {
  description = "RDS engine version"
  type        = string
  default     = "16"
}

variable "create_alb" {
  description = "Whether to create an ALB (set false if you plan to use an existing ALB)"
  type        = bool
  default     = true
}

variable "create_ecr" {
  description = "Whether to create an ECR repository"
  type        = bool
  default     = true
}

variable "container_port" {
  description = "Port your Django container listens on"
  type        = number
  default     = 8000
}

variable "task_cpu" {
  description = "Task CPU for Fargate"
  type        = string
  default     = "512"
}

variable "task_memory" {
  description = "Task memory for Fargate"
  type        = string
  default     = "1024"
}
