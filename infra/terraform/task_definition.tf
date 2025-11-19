# ECS Task definition (Fargate). This is a lightweight example — expand for your needs.
resource "aws_ecs_task_definition" "app" {
  family                   = "${var.project_name}-${var.env}-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "web"
      image     = "${aws_ecr_repository.app.repository_url}:latest"
      essential = true
      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "web"
        }
      }
      environment = [
        {
          name  = "DJANGO_SETTINGS_MODULE"
          value = "water_delivery.settings_production"
        }
      ]
      secrets = var.use_secrets_manager ? [
        {
          name      = "DB_USERNAME"
          valueFrom = "${aws_secretsmanager_secret.db[0].arn}:SecretString:username"
        },
        {
          name      = "DB_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.db[0].arn}:SecretString:password"
        }
      ] : []
    }
  ])
}

# IMPORTANT: This task definition references the ECR repo. If you already push images manually,
# set the image tag appropriately (not always :latest).
