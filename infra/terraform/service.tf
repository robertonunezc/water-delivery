# Application Load Balancer (optional) + ECS Service

resource "aws_lb" "app_alb" {
  count               = var.create_alb ? 1 : 0
  name                = "${var.project_name}-${var.env}-alb"
  internal            = false
  load_balancer_type  = "application"
  security_groups     = [aws_security_group.alb_sg.id]
  subnets             = var.public_subnet_ids

  tags = {
    Name = "${var.project_name}-${var.env}-alb"
  }
}

resource "aws_lb_target_group" "app_tg" {
  count    = var.create_alb ? 1 : 0
  name     = "${var.project_name}-${var.env}-tg"
  port     = var.container_port
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  health_check {
    path                = "/"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    interval            = 30
    matcher             = "200-399"
  }
}

resource "aws_lb_listener" "http" {
  count = var.create_alb ? 1 : 0
  load_balancer_arn = aws_lb.app_alb[0].arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app_tg[0].arn
  }
}

resource "aws_ecs_service" "app" {
  name            = "${var.project_name}-${var.env}-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.create_private_subnets ? aws_subnet.private[*].id : var.private_subnet_ids
    security_groups = [aws_security_group.ecs_sg.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.create_alb ? aws_lb_target_group.app_tg[0].arn : null
    container_name   = "web"
    container_port   = var.container_port
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  depends_on = [aws_lb_listener.http]
}
