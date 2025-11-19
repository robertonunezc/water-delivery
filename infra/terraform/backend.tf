# Example S3 backend configuration (optional).
# Uncomment and set values to enable remote state with S3 + DynamoDB locking.

# terraform {
#   backend "s3" {
#     bucket         = "<your-terraform-state-bucket>"
#     key            = "infra/terraform.tfstate"
#     region         = "us-east-1"
#     dynamodb_table = "<your-lock-table>"
#     encrypt        = true
#   }
# }

# Note: you told me Remote state backend: Not sure for now — leaving backend disabled.
# If you want to enable remote state later, provide S3 bucket and (recommended) DynamoDB table.
