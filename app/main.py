"""
Toy SRE demo service.
Exposes deliberately imperfect endpoints so we have something real
to alert on, chase in a runbook, and write a postmortem about.
"""
import random
import time

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

app = FastAPI(title="solo-sre")

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "Request latency", ["path"]
)

LANDING_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Solo-SRE</title>
<style>
  body { background:#0f1115; color:#e6e6e6; font-family:-apple-system,Segoe UI,sans-serif;
         max-width:700px; margin:60px auto; padding:0 20px; line-height:1.6; }
  h1 { color:#7ee787; }
  .status { display:inline-block; padding:4px 10px; background:#1a3a1a; color:#7ee787;
            border-radius:4px; font-size:14px; }
  a { color:#58a6ff; text-decoration:none; }
  a:hover { text-decoration:underline; }
  code { background:#1a1d24; padding:2px 6px; border-radius:3px; }
  ul { padding-left:20px; }
  .footer { margin-top:40px; color:#8b949e; font-size:14px; }
</style>
</head>
<body>
  <h1>Solo-SRE <span class="status">running</span></h1>
  <p>A toy service instrumented for a full SRE lifecycle demo &mdash;
     CI/CD, TLS, observability, and incident response, all running on
     a single free-tier VM.</p>
  <ul>
    <li><a href="/health">/health</a> &mdash; liveness check</li>
    <li><a href="/metrics">/metrics</a> &mdash; Prometheus metrics (basic auth required)</li>
    <li><a href="/slow">/slow</a> &mdash; randomized latency, for burn-rate demos</li>
    <li><a href="/error">/error</a> &mdash; ~30% failure rate, for error-budget demos</li>
  </ul>
  <p>Source, architecture, and incident writeups:
     <a href="https://github.com/YOUR_USERNAME/solo-sre">GitHub</a></p>
  <div class="footer">Deployed via GitHub Actions CI/CD. Every deploy is
    git-SHA tagged and health-check gated with automatic rollback.</div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def root():
    start = time.time()
    REQUEST_COUNT.labels(path="/", status="200").inc()
    REQUEST_LATENCY.labels(path="/").observe(time.time() - start)
    return LANDING_PAGE


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/slow")
def slow():
    """Randomly slow endpoint - useful for latency SLO / burn-rate demos."""
    start = time.time()
    delay = random.choice([0.05, 0.1, 0.3, 0.8, 1.5])
    time.sleep(delay)
    REQUEST_COUNT.labels(path="/slow", status="200").inc()
    REQUEST_LATENCY.labels(path="/slow").observe(time.time() - start)
    return {"delayed_seconds": delay}


@app.get("/error")
def error():
    """Randomly fails ~30% of the time - useful for error-budget demos."""
    start = time.time()
    if random.random() < 0.3:
        REQUEST_COUNT.labels(path="/error", status="500").inc()
        REQUEST_LATENCY.labels(path="/error").observe(time.time() - start)
        return Response(content='{"error": "simulated failure"}', status_code=500,
                         media_type="application/json")
    REQUEST_COUNT.labels(path="/error", status="200").inc()
    REQUEST_LATENCY.labels(path="/error").observe(time.time() - start)
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)