# SLIs / SLOs / error budget

## Service level indicators
| SLI | Definition |
|---|---|
| Availability | % of requests to `/` and `/health` returning non-5xx |
| Latency | p95 request duration for `/` and `/slow`, from `http_request_duration_seconds` |
| Error rate | % of `/error` requests returning 5xx (this endpoint fails ~30% on purpose - it's the demo's error-budget generator) |

## SLOs (30-day rolling window)
- **Availability:** 99.0% (deliberately looser than a real prod SLO - single VM, single AZ, no redundancy, and that constraint should be stated explicitly rather than hidden)
- **Latency:** p95 < 500ms on `/`
- **Error budget:** 1% of requests may fail before the budget is exhausted

## Burn-rate alerting
Configure two alert rules in Grafana Cloud (free tier includes alerting):
- **Fast burn:** > 14.4x burn rate over 1h -> page immediately (would exhaust a 30-day budget in ~2 days)
- **Slow burn:** > 3x burn rate over 6h -> ticket, not page

Route both to a free webhook (Discord or Telegram bot) - no PagerDuty needed to demonstrate the concept.

## RED method (per service - the app)
Already instrumented in `app/main.py` via `Counter`/`Histogram`. Build these as Grafana panels:
- **Rate:** `sum(rate(http_requests_total[5m])) by (path)`
- **Errors:** `sum(rate(http_requests_total{status="500"}[5m])) by (path)`
- **Duration (p50/p95):** `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, path))` (swap `0.95` for `0.5` for p50)

## USE method (per resource - the host)
Data already flows from `node-exporter` via `vmagent`; not yet turned into panels. One row per resource:
| Resource | Utilization | Saturation | Errors |
|---|---|---|---|
| CPU | `1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))` | `node_load1 / count(node_cpu_seconds_total{mode="idle"})` | n/a |
| Memory | `1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)` | swap usage (`node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes`) | OOM kill count (from `docker events` or container restart count) |
| Disk | `1 - (node_filesystem_avail_bytes / node_filesystem_size_bytes)` | disk I/O queue depth | filesystem errors (rare on a single VM, but check `node_filesystem_readonly`) |

On an e2.micro, CPU saturation and memory/swap are the two that will actually bite you first - that's the pair worth alerting on.

## Why these numbers
99.0% instead of 99.9%+ because a single e2.micro with no redundancy
genuinely cannot promise more than that - claiming a tighter SLO here
would be dishonest. That reasoning is more valuable to show than a
copy-pasted "five nines" target.
