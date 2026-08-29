# Runbook

## Alert: high error rate on /error
1. Check dashboard for current error rate and whether it's within the
   expected ~30% baseline (the endpoint is designed to fail sometimes)
   or has jumped higher.
2. `docker logs app --tail 100` on the VM.
3. If genuinely elevated, check `docker stats` for memory pressure -
   app has a 150m mem_limit and could be getting throttled/OOM-killed.
4. If OOM-killed: `docker ps -a | grep app`, confirm exit code 137,
   then `docker compose up -d --no-deps app` to restart, or
   `scripts/rollback.sh` if it started after a recent deploy.

## Alert: high p95 latency on /slow or /
1. Check `docker stats` for CPU throttling (e2.micro has 1/8 OCPU
   burstable - sustained load can exhaust the burst credit).
2. Check swap usage (`free -h`) - if swapping heavily, latency spikes
   are expected; this is the tradeoff documented in architecture.md.
3. If it correlates with a recent deploy, roll back:
   `./scripts/rollback.sh`

## Alert: app container down / health check failing
1. `docker ps -a` - check exit code.
2. `docker compose up -d --no-deps app`
3. If it won't stay up, check `docker logs app` for a crash loop, and
   `./scripts/rollback.sh` to the last known-good image tag.

## Scenario: VM unreachable entirely
1. Check OCI console - instance state, whether it was reclaimed
   (Always Free tier can reclaim idle instances under some conditions -
   worth checking OCI's current policy).
2. Check NSG/Security List wasn't modified outside of Terraform
   (`terraform plan` should show no drift).
