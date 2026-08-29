"""
Toy SRE demo service.
Exposes deliberately imperfect endpoints so we have something real
to alert on, chase in a runbook, and write a postmortem about.
"""
import random
import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest


app = FastAPI(title="solo-sre")

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "Request latency", ["path"]
)


@app.get("/")
def root():
    start = time.time()
    REQUEST_COUNT.labels(path="/", status="200").inc()
    REQUEST_LATENCY.labels(path="/").observe(time.time() - start)
    return {"service": "solo-sre", "status": "ok"}


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
