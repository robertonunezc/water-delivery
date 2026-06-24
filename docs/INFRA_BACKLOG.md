# Infrastructure Improvement Backlog

## Current production baseline

- Provider: Cloudfanatic
- Topology: single VPS
- Traffic flow: `nginx -> Django/Gunicorn container`
- Database: PostgreSQL in Docker on the same VPS
- Queue/cache: Redis in Docker on the same VPS
- Deployment method: GitHub Actions + SSH + Docker Compose
- Backup method today: manual/periodic `pg_dump` sent by email
- Multi-tenancy: enabled with `django-tenants`

## Main operational risks today

- A single VPS failure can take down app, database, logs, and local Docker volumes at once.
- Deployments currently allow production changes without test enforcement.
- The health check path is not reliable after the multi-tenant change.
- Production settings still rely on unsafe fallbacks.
- Backups are not off-host, not restore-tested, and not monitored.
- Observability is partial: logs exist, but metrics and alerting are not complete.

## Principles for this backlog

- Optimize for a stable single-VPS operation first.
- Prefer simple, repeatable automation over half-finished platform migration work.
- Every change should end with a written runbook and a verification step.
- Backups are only considered valid after a restore test.

## Weekly roadmap

### Week 1: Define and freeze the production operating model

Goal:
Create one accurate source of truth for production infrastructure and stop treating inactive AWS/ECS/Terraform paths as current production.

Tasks:
- Document the real production architecture.
- Document all running services, ports, domains, volumes, and secrets.
- Mark `AWS/ECS/Terraform` files as inactive or future work.
- Create a production operations runbook.
- Inventory current Docker volumes and disk usage on the VPS.

Acceptance criteria:
- A teammate can read one document and understand how production is deployed.
- There is no ambiguity about whether production runs on VPS or ECS.
- Existing operational dependencies are listed: app, nginx, postgres, redis, GitHub Actions.

Suggested deliverables:
- `docs/OPERATIONS.md`
- `docs/PRODUCTION_ARCHITECTURE.md`

Suggested commands:

```bash
docker ps
docker volume ls
docker system df
df -h
free -m
```

### Week 2: Restore reliable health checks

Goal:
Make health checks work with multi-tenancy and use them in deploy validation.

Tasks:
- Add a liveness endpoint that only verifies the app process is serving traffic.
- Add a readiness endpoint that verifies database and Redis connectivity safely.
- Ensure readiness works from the public schema and does not depend on tenant hostname routing.
- Update nginx to proxy the correct health endpoint.
- Update GitHub Actions deploy smoke test to call the real URL and port.

Acceptance criteria:
- `curl` to the liveness endpoint returns `200` consistently.
- `curl` to the readiness endpoint returns `200` only when app, DB, and Redis are healthy.
- Deployment pipeline fails if readiness fails.
- Health checks work after the multi-tenant middleware path is evaluated.

Suggested deliverables:
- Application health endpoint design
- Nginx config update
- Deploy workflow smoke-test update

Suggested commands:

```bash
curl -i http://localhost:8000/health/live
curl -i http://localhost:8000/health/ready
docker-compose --env-file .env.production -f docker-compose.prod.yml logs -f web
```

### Week 3: Make deployments safe and reversible

Goal:
Stop destructive deploy behavior and establish a rollback-ready release flow.

Tasks:
- Re-enable CI tests before deployment.
- Remove the `SKIP_TESTS=true` production path.
- Tag Docker images with commit SHA.
- Keep a stable release tag and a previous-known-good tag.
- Replace full `docker-compose down` with service-level rolling or restart-based deployment.
- Define rollback steps using the prior image tag.

Acceptance criteria:
- Production deployment does not proceed if tests fail.
- A failed release can be rolled back in minutes.
- Deployments do not require bringing down Postgres and Redis.
- The deployed image can be traced to a commit.

Suggested deliverables:
- Updated GitHub Actions workflow
- Rollback runbook section

Suggested commands:

```bash
docker image ls
docker-compose --env-file .env.production -f docker-compose.prod.yml pull web celery-worker celery-beat
docker-compose --env-file .env.production -f docker-compose.prod.yml up -d web celery-worker celery-beat
```

### Week 4: Harden production configuration and secret handling

Goal:
Fail fast on missing production config and remove unsafe defaults.

Tasks:
- Require `SECRET_KEY` in production.
- Remove `ALLOWED_HOSTS='*'` default behavior for production.
- Make `CSRF_TRUSTED_ORIGINS` env-driven only.
- Review all production env vars and write them explicitly in documentation.
- Ensure GitHub Actions writes every required production variable.
- Review Sentry initialization and secret ownership.

Acceptance criteria:
- Production startup fails with a clear error if critical env vars are missing.
- No production secret depends on a code fallback.
- Allowed hosts and CSRF origins are explicit and documented.

Suggested deliverables:
- Hardened Django settings
- Environment variable reference table

### Week 5: Replace email backups with off-host automated backups

Goal:
Move to automated PostgreSQL backups stored outside the VPS.

Tasks:
- Choose backup target: `S3`, `Backblaze B2`, or `Cloudflare R2`.
- Create a scheduled backup job using `pg_dump`.
- Compress and encrypt backup artifacts.
- Store backups off-host.
- Retain daily, weekly, and monthly snapshots.
- Log each backup result.

Acceptance criteria:
- Backups run automatically without manual intervention.
- Backups are encrypted and stored outside the VPS.
- Retention policy is documented and applied.
- Backup failures are visible in logs.

Suggested retention:
- Daily: 30 days
- Weekly: 8 to 12 weeks
- Monthly: 6 to 12 months

Suggested deliverables:
- `scripts/backup_postgres.sh`
- `docs/BACKUP_AND_RESTORE.md`
- Cron or systemd timer definition

Example command baseline:

```bash
pg_dump -Fc -h localhost -p 5438 -U "$POSTGRES_USER" "$POSTGRES_DB" > backup.dump
```

### Week 6: Prove restores and define RPO/RTO

Goal:
Turn backup into a tested recovery process.

Tasks:
- Restore the latest backup into a fresh test database.
- Validate schema, public tenant, and tenant data.
- Measure recovery time.
- Define target `RPO` and `RTO`.
- Write a step-by-step restore runbook.

Acceptance criteria:
- A restore test is performed successfully end to end.
- Recovery time is measured and recorded.
- The team knows the maximum acceptable data loss and recovery window.

Suggested deliverables:
- Restore checklist
- Recovery timing notes

Suggested commands:

```bash
createdb restore_test
pg_restore -d restore_test backup.dump
```

### Week 7: Add host-level monitoring

Goal:
Detect VPS-level failures before they become outages.

Tasks:
- Monitor CPU, RAM, disk, inode usage, load average, and uptime.
- Monitor Docker container restart counts.
- Monitor filesystem growth for logs and database volumes.
- Add a simple dashboard or hosted metrics target.

Acceptance criteria:
- You can see VPS resource usage over time.
- Disk growth and container restart spikes are visible.
- You have at least one alert for disk pressure.

Recommended metrics:
- CPU usage
- Memory usage
- Disk usage
- Inodes
- Container restarts
- Host load

### Week 8: Add application, database, and queue metrics

Goal:
Move from log-only troubleshooting to active service monitoring.

Tasks:
- Add Django request metrics.
- Add Postgres metrics.
- Add Redis metrics.
- Add Celery queue and worker metrics.
- Add nginx request/error metrics if practical.
- Create a basic operations dashboard.

Acceptance criteria:
- You can see latency, error rate, throughput, queue backlog, and DB health.
- Celery worker issues are visible without reading raw logs.

Recommended dashboard panels:
- Request count
- P95 latency
- 5xx rate
- Celery queue depth
- Failed task count
- DB connections
- Redis memory

### Week 9: Create real alerting

Goal:
Route important production problems to a channel the team actually checks.

Tasks:
- Select the alert destination: email, Telegram, Slack, or PagerDuty-like system.
- Add alerts for service unavailability.
- Add alerts for backup failures or missing backups.
- Add alerts for disk pressure.
- Add alerts for abnormal error rates.
- Add alerts for queue backlog.

Acceptance criteria:
- You receive an alert when the app is down.
- You receive an alert when backups fail.
- You receive an alert before disk exhaustion causes downtime.

Minimum alerts:
- Web health endpoint failing
- Postgres container down
- Celery worker down
- Backup job failed
- Backup missing for more than 24h
- Disk usage above 80%
- Sustained 5xx spike

### Week 10: Harden VPS and containers

Goal:
Reduce avoidable security risk on the single host.

Tasks:
- Confirm Postgres and Redis are not publicly exposed.
- Review firewall rules.
- Review SSH access, keys, and root login policy.
- Add automated OS security updates if acceptable.
- Run app containers as non-root where practical.
- Add Docker image vulnerability scanning.
- Review Docker socket exposure and host mounts.

Acceptance criteria:
- Database and Redis are reachable only from intended paths.
- SSH posture is documented and hardened.
- The app image is scanned regularly.

Checklist:
- SSH keys only
- Password auth disabled if possible
- Firewall enabled
- Least-privilege container runtime
- No unnecessary public ports

### Week 11: Standardize automation for single-VPS operations

Goal:
Choose one automation path and make it complete.

Tasks:
- Decide between `shell scripts + docker-compose` or `Ansible + docker-compose`.
- Remove placeholder automation that is not used.
- Automate bootstrap for a fresh VPS.
- Automate application update steps.
- Automate observability agent setup.

Acceptance criteria:
- A new VPS can be prepared from documented automation.
- The team has one approved deploy path.
- Unused IaC/deployment artifacts are removed or clearly archived.

Suggested deliverables:
- `infra/ansible/` completed, or
- `scripts/bootstrap_vps.sh` and `scripts/deploy_prod.sh`

### Week 12: Build the operating runbook and review cadence

Goal:
Create a repeatable DevOps operating rhythm for the team.

Tasks:
- Write runbooks for deploy, rollback, restart, backup, restore, and incident response.
- Define weekly checks for backups, disk, failed jobs, and deploy status.
- Define monthly checks for patching, secret rotation review, and capacity.
- Define ownership for production operations.

Acceptance criteria:
- Another engineer can execute the main production procedures from docs.
- Routine maintenance tasks have an owner and cadence.
- Infrastructure work is no longer ad hoc.

## Backlog by category

### Infrastructure

- Keep one active production model: VPS + nginx + Docker Compose.
- Remove or archive inactive ECS/Terraform workflow paths.
- Tag images by commit SHA.
- Avoid shutting down the full stack during normal deploys.
- Keep Postgres and Redis on private-only exposure paths.
- Measure disk usage of Docker volumes regularly.

### Observability

- Keep structured JSON logs.
- Add host metrics.
- Add Django, Postgres, Redis, and Celery metrics.
- Add dashboards for service health and capacity.
- Separate liveness and readiness.
- Add actionable alerts tied to symptoms.

### Backups

- Stop using email as the primary backup delivery mechanism.
- Back up Postgres to off-host encrypted storage.
- Define retention clearly.
- Test restores monthly.
- Alert on missing or failed backups.
- Document tenant-aware restore validation.

### DevOps

- Re-enable mandatory tests in CI.
- Use immutable image tags.
- Add rollback-by-tag.
- Fail deploy on health-check failure.
- Standardize production env generation.
- Keep one deploy workflow and one runbook.

## Suggested ownership model

- DevOps owner: production deploy, host hardening, backup automation, monitoring
- Backend owner: Django health endpoints, config hardening, Celery instrumentation
- Shared ownership: restore tests, incident runbooks, release verification

## Suggested monthly review checklist

- Were backups created every day?
- Was at least one restore tested this month?
- Are disk usage and Docker volumes within safe limits?
- Did any deploy fail or require manual repair?
- Are there unresolved container restart loops?
- Are alert thresholds still useful?
- Are production secrets and access still appropriate?

## Immediate next actions

These are the first items to execute from this backlog:

1. Week 1 documentation cleanup
2. Week 2 multi-tenant-safe health checks
3. Week 3 deployment safety fixes
4. Week 5 off-host backup automation
5. Week 6 restore test
