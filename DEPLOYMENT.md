**AWS ECS Deployment**

Required GitHub repository secrets:
- `AWS_ROLE_TO_ASSUME`: IAM Role ARN to assume for deployment (optional if using access keys).
- `AWS_REGION`: AWS region, e.g. `us-east-1`.
- `ECR_REGISTRY`: ECR registry URI, e.g. `123456789012.dkr.ecr.us-east-1.amazonaws.com`.
- `ECR_REPOSITORY`: ECR repository name, e.g. `water-delivery`.
- `ECS_CLUSTER`: ECS cluster name where the service runs.
- `ECS_SERVICE`: ECS service name to update.
- `ECS_EXECUTION_ROLE_ARN`: Task execution role ARN for the task definition.
- `ECS_TASK_ROLE_ARN`: Task role ARN for the task definition.

Notes and setup commands (run locally / in CI with AWS CLI configured):

1. Create ECR repository (if not present):

```bash
aws ecr create-repository --repository-name ${ECR_REPOSITORY} --region ${AWS_REGION}
```

2. Get ECR registry URI:

```bash
aws ecr describe-repositories --repository-names ${ECR_REPOSITORY} --region ${AWS_REGION} --query "repositories[0].repositoryUri" --output text
```

3. EC2-specific ECS setup (since you chose EC2 launch type):

- Use an ECS-optimized AMI or Amazon Linux 2 with the ECS agent installed. Example when creating a launch template or AMI selection in an ASG.
- Create an IAM instance profile for the EC2 instances with permissions to pull images from ECR and push logs to CloudWatch Logs (e.g., `AmazonEC2ContainerServiceforEC2Role`, `AmazonEC2ContainerRegistryReadOnly`, and `CloudWatchLogsFullAccess` or more restricted policies).
- Create an Auto Scaling Group (ASG) with the ECS-optimized AMI, and make sure instances join the ECS cluster using the cluster name in `/etc/ecs/ecs.config` or via user data.
- If your tasks use host ports (bridge/host networking), ensure the ALB target group type is `instance`. If you keep `awsvpc`, use `ip` target type.

4. Ensure ECR and ECS IAM roles exist and grant permissions to pull logs and run tasks.

5. Add the required secrets to the GitHub repository settings (Settings → Secrets → Actions).

Triggering the workflow:
- The workflow runs on push to `main` and can be triggered manually from the Actions tab (`workflow_dispatch`).

Troubleshooting:
- If the job fails at login/push, check that the runner can assume the provided role and that the ECR registry value is correct.
- If tasks do not start, confirm EC2 instances are `ACTIVE` in the ECS cluster and have the correct instance profile and IAM permissions.
- For more verbose AWS CLI output, set `AWS_DEBUG=1` in the environment.

Environment-specific Django settings
- Set the `DJANGO_SETTINGS_MODULE` environment variable to select which Django settings module to use.

- Local development example:

```bash
export DJANGO_SETTINGS_MODULE=water_delivery.settings_development
python manage.py runserver
```

- ECS task definition / container example:

Add an environment variable to your container definition (or use Secrets Manager):

```json
{ "name": "DJANGO_SETTINGS_MODULE", "value": "water_delivery.settings_production" }
```

Or set it in the `env` section of the ECS task definition template used by the workflow.

Note: `settings_production.py` imports from the base `settings.py` and applies production overrides. Keep secrets like `DJANGO_SECRET_KEY` in environment variables or a secrets store.

Secrets Manager + GitHub Actions setup

1. Create the secrets in AWS Secrets Manager (example):

```bash
aws secretsmanager create-secret --name water-delivery/DJANGO_SECRET_KEY --secret-string '{"DJANGO_SECRET_KEY":"super-secret"}' --region ${AWS_REGION}
aws secretsmanager create-secret --name water-delivery/POSTGRES_PASSWORD --secret-string '{"POSTGRES_PASSWORD":"super-secret-db-pass"}' --region ${AWS_REGION}
```

2. Get each secret's ARN and add them as GitHub secrets (store ARNs, not the secret values):

```bash
aws secretsmanager describe-secret --secret-id water-delivery/DJANGO_SECRET_KEY --region ${AWS_REGION} --query 'ARN' --output text
aws secretsmanager describe-secret --secret-id water-delivery/POSTGRES_PASSWORD --region ${AWS_REGION} --query 'ARN' --output text
```

Set the following GitHub secrets:
- `DJANGO_SECRET_ARN` → ARN returned for `water-delivery/DJANGO_SECRET_KEY`
- `POSTGRES_PASSWORD_ARN` → ARN returned for `water-delivery/POSTGRES_PASSWORD`

3. Ensure the ECS task execution role (or EC2 instance profile) has permission to read these secrets:

Attach a policy allowing `secretsmanager:GetSecretValue` and `secretsmanager:DescribeSecret` on the secret ARNs.

