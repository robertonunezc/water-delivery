# IAM role for ECS task execution (allows pulling from ECR and writing logs)
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project_name}-${var.env}-ecs-task-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "task_execution_attachment" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Task role (for application to assume, e.g., to access S3/SecretsManager if needed)
resource "aws_iam_role" "ecs_task_role" {
  name = "${var.project_name}-${var.env}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

# Attach minimal inline policy placeholder (update with least-privilege policies as needed)
resource "aws_iam_role_policy" "ecs_task_role_policy" {
  name = "${var.project_name}-${var.env}-ecs-task-role-policy"
  role = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = "*"
      }
    ]
  })
}

# Allow the ECS task role to read the DB secret (if created)
resource "aws_iam_role_policy" "ecs_task_secrets_access" {
  count = var.use_secrets_manager ? 1 : 0
  name  = "${var.project_name}-${var.env}-ecs-task-secrets-access"
  role  = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = aws_secretsmanager_secret.db[0].arn
      }
    ]
  })
}
