resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.env}-cluster"

  tags = {
    Name = "${var.project_name}-${var.env}-cluster"
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}-${var.env}"
  retention_in_days = 30
}
