resource "aws_ecr_repository" "app" {
  count               = var.create_ecr ? 1 : 0
  name                = "${var.project_name}-${var.env}"
  image_tag_mutability = "MUTABLE"

  lifecycle {
    prevent_destroy = false
  }

  tags = {
    Name = "${var.project_name}-${var.env}-ecr"
  }
}
