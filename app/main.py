"""
Devkit - small, stateless developer utilities behind one API.

Also used as the reference workload for a multi-region EKS / GitOps /
observability setup, which is why it ships metrics, traces and probes.

Configuration (all optional, via environment):
  APP_VERSION                  version string reported by /status
  MAX_TEXT                     max input length for tool endpoints (default 10000)
  RATE_LIMIT_PER_MIN           per-IP requests/min on /api/* (default 60, 0 = off)
  TRUSTED_PROXY_HOPS           number of trusted proxies in front of the app
                               (default 0 = ignore X-Forwarded-For entirely)
  OTEL_EXPORTER_OTLP_ENDPOINT  enable tracing when set (e.g. http://otel:4318)
  UPSTREAM_URL                 optional downstream service used by /greet
  UPSTREAM_REQUIRED            "true" makes /readyz depend on the upstream
  CHAOS_ENABLED                "true" exposes /_chaos/* fault endpoints
"""

import base64
import binascii
import hashlib
import json
import logging
import os
import secrets
import string
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from urllib.parse import quote, unquote

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

log = logging.getLogger("devkit")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes", "on")


VERSION = os.getenv("APP_VERSION", "dev")
MAX_TEXT = int(os.getenv("MAX_TEXT", "10000"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
UPSTREAM_URL = os.getenv("UPSTREAM_URL", "").rstrip("/")
UPSTREAM_REQUIRED = _flag("UPSTREAM_REQUIRED")
CHAOS_ENABLED = _flag("CHAOS_ENABLED")

HASH_ALGOS = {"md5", "sha1", "sha256", "sha512"}
OPS_PATHS = {"/metrics", "/healthz", "/readyz"}
START_TIME = time.time()


# --------------------------------------------------------------------------
# App + telemetry (tracing is opt-in and never blocks startup)
# --------------------------------------------------------------------------
app = FastAPI(title="devkit", version=VERSION)


def setup_tracing(application: FastAPI) -> None:
    if not OTLP_ENDPOINT:
        log.info("tracing disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": "devkit", "service.version": VERSION}
            )
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(
            application, excluded_urls="healthz,readyz,metrics"
        )
        HTTPXClientInstrumentor().instrument()
        log.info("tracing enabled -> %s", OTLP_ENDPOINT)
    except Exception:  # observability must never take the app down
        log.exception("tracing setup failed; continuing without it")


setup_tracing(app)

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "Request latency", ["method", "path"]
)


# --------------------------------------------------------------------------
# Client IP + rate limiting
# --------------------------------------------------------------------------
def get_client_ip(request: Request) -> str:
    """Only trust X-Forwarded-For when we know how many proxies sit in front.

    Each trusted proxy appends the address it saw, so the real client is the
    Nth entry from the right, never the leftmost (which the client controls).
    """
    direct = request.client.host if request.client else "unknown"
    if TRUSTED_PROXY_HOPS <= 0:
        return direct
    parts = [
        p.strip()
        for p in request.headers.get("x-forwarded-for", "").split(",")
        if p.strip()
    ]
    if len(parts) >= TRUSTED_PROXY_HOPS:
        return parts[-TRUSTED_PROXY_HOPS]
    return direct


class SlidingWindowLimiter:
    """In-memory per-key limiter. Per replica: with N pods the effective
    limit is N x limit. Use a shared store (Redis) or the ingress if you need
    a global limit."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque] = {}
        self._last_prune = time.monotonic()

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        q = self.hits.setdefault(key, deque())
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False, max(1, int(self.window - (now - q[0])) + 1)
        q.append(now)
        self._maybe_prune(now)
        return True, 0

    def _maybe_prune(self, now: float) -> None:
        if now - self._last_prune < self.window:
            return
        self._last_prune = now
        for key in [
            k for k, q in self.hits.items() if not q or now - q[-1] > self.window
        ]:
            del self.hits[key]


limiter = SlidingWindowLimiter(RATE_LIMIT_PER_MIN) if RATE_LIMIT_PER_MIN > 0 else None


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if limiter and request.url.path.startswith("/api/"):
        ok, retry_after = limiter.check(get_client_ip(request))
        if not ok:
            return JSONResponse(
                {"error": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
    return await call_next(request)


# Added last so it is outermost and also records 429s.
@app.middleware("http")
async def record_metrics(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        path = route.path if route else "unmatched"  # template, not raw URL
        if request.url.path not in OPS_PATHS:
            REQUEST_COUNT.labels(request.method, path, str(status)).inc()
            REQUEST_LATENCY.labels(request.method, path).observe(
                time.perf_counter() - start
            )


# --------------------------------------------------------------------------
# Landing page
# --------------------------------------------------------------------------
LANDING_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Devkit</title>
<style>
  :root { --bg:#ffffff; --fg:#1b1f24; --muted:#5b6570; --card:#f5f7fa;
          --line:#dde2e8; --accent:#2563eb; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1115; --fg:#e6e8eb; --muted:#8b95a1; --card:#171a20;
            --line:#262b33; --accent:#60a5fa; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); line-height:1.55;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  main { max-width:820px; margin:0 auto; padding:56px 20px 40px; }
  h1 { font-size:30px; margin:0 0 6px; letter-spacing:-0.02em; }
  .sub { color:var(--muted); margin:0 0 32px; }
  .grid { display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }
  .card h2 { font-size:15px; margin:0 0 4px; }
  .card p { font-size:13px; color:var(--muted); margin:0 0 10px; }
  input, select, button { font:inherit; font-size:14px; border-radius:6px;
          border:1px solid var(--line); background:var(--bg); color:var(--fg); padding:7px 10px; }
  input { width:100%; margin-bottom:8px; }
  .row { display:flex; gap:8px; }
  button { background:var(--accent); color:#fff; border-color:var(--accent); cursor:pointer; }
  pre { margin:10px 0 0; padding:10px; border-radius:6px; background:var(--bg);
        border:1px solid var(--line); font-size:12px; min-height:38px;
        white-space:pre-wrap; word-break:break-all; }
  footer { margin-top:36px; font-size:13px; color:var(--muted); }
  footer a { color:var(--accent); text-decoration:none; }
</style>
</head>
<body>
<main>
  <h1>Devkit</h1>
  <p class="sub">Small, fast utilities for everyday development work. No sign-up.</p>
  <div class="grid" id="grid"></div>
  <footer>
    <a href="/status">Status</a> &middot;
    <a href="/docs">API docs</a> &middot;
    <a href="https://github.com/E-Vanika/cloud-playground">Source</a>
  </footer>
</main>
<script>
  const q = (s) => encodeURIComponent(s);
  const TOOLS = [
    { title:"UUID", desc:"Generate a random v4 UUID.", btn:"Generate",
      run:() => ["GET","/api/uuid"] },
    { title:"Hash", desc:"Hash text with a common algorithm.", btn:"Hash",
      input:"Text to hash", select:["sha256","sha512","sha1","md5"],
      run:(t,s) => ["GET",`/api/hash?text=${q(t)}&algo=${s}`] },
    { title:"Base64", desc:"Encode or decode text.", btn:"Run",
      input:"Text", select:["encode","decode"],
      run:(t,s) => ["GET",`/api/base64?text=${q(t)}&mode=${s}`] },
    { title:"URL encode", desc:"Percent-encode or decode a string.", btn:"Run",
      input:"Text", select:["encode","decode"],
      run:(t,s) => ["GET",`/api/url?text=${q(t)}&mode=${s}`] },
    { title:"JSON", desc:"Validate and pretty-print JSON.", btn:"Format",
      input:'{"a":1}',
      run:(t) => ["POST","/api/json",{text:t}] },
    { title:"JWT decode", desc:"Decode header and payload. Does not verify.", btn:"Decode",
      input:"eyJhbGciOi...",
      run:(t) => ["POST","/api/jwt/decode",{token:t}] },
    { title:"Token", desc:"Cryptographically random token.", btn:"Generate",
      select:["urlsafe","hex","password"],
      run:(t,s) => ["GET",`/api/token?kind=${s}`] },
    { title:"Your IP", desc:"The address your request came from.", btn:"Show",
      run:() => ["GET","/api/ip"] },
    { title:"Unix time", desc:"Current epoch seconds and ISO 8601.", btn:"Show",
      run:() => ["GET","/api/time"] },
  ];

  async function call([method, url, body], out) {
    out.textContent = "...";
    try {
      const r = await fetch(url, method === "POST"
        ? { method, headers:{ "Content-Type":"application/json" }, body:JSON.stringify(body) }
        : undefined);
      const t = await r.text();
      try { out.textContent = JSON.stringify(JSON.parse(t), null, 2); }
      catch (e) { out.textContent = t; }
    } catch (e) { out.textContent = "Request failed"; }
  }

  const grid = document.getElementById("grid");
  for (const t of TOOLS) {
    const card = document.createElement("section");
    card.className = "card";
    card.innerHTML = `<h2></h2><p></p>`;
    card.querySelector("h2").textContent = t.title;
    card.querySelector("p").textContent = t.desc;
    let input = null, select = null;
    if (t.input) {
      input = document.createElement("input");
      input.placeholder = t.input;
      input.maxLength = 10000;
      card.appendChild(input);
    }
    const row = document.createElement("div");
    row.className = "row";
    if (t.select) {
      select = document.createElement("select");
      for (const o of t.select) select.add(new Option(o, o));
      row.appendChild(select);
    }
    const btn = document.createElement("button");
    btn.textContent = t.btn;
    row.appendChild(btn);
    card.appendChild(row);
    const out = document.createElement("pre");
    card.appendChild(out);
    btn.onclick = () => call(t.run(input ? input.value : "", select ? select.value : ""), out);
    grid.appendChild(card);
  }
</script>
</body>
</html>"""


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class JsonIn(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT)


class JwtIn(BaseModel):
    token: str = Field(..., max_length=MAX_TEXT)


# --------------------------------------------------------------------------
# Ops endpoints
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    return LANDING_PAGE


@app.get("/healthz")
def healthz():
    """Liveness: the process is up and serving. Never checks dependencies."""
    return {"status": "alive"}


@app.get("/readyz")
def readyz():
    """Readiness: safe to receive traffic. Upstream only matters if required."""
    if UPSTREAM_URL and UPSTREAM_REQUIRED:
        try:
            httpx.get(f"{UPSTREAM_URL}/healthz", timeout=2.0).raise_for_status()
        except httpx.HTTPError:
            return JSONResponse(
                {"status": "not ready", "reason": "upstream"}, status_code=503
            )
    return {"status": "ready"}


@app.get("/status")
def status():
    return {
        "status": "ok",
        "version": VERSION,
        "uptime_seconds": int(time.time() - START_TIME),
    }


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --------------------------------------------------------------------------
# Tool endpoints
# --------------------------------------------------------------------------
@app.get("/api/uuid")
def new_uuid():
    return {"uuid": str(uuid.uuid4())}


@app.get("/api/time")
def now():
    ts = time.time()
    return {
        "unix": int(ts),
        "iso": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
    }


@app.get("/api/ip")
def client_ip(request: Request):
    return {"ip": get_client_ip(request)}


@app.get("/api/hash")
def hash_text(text: str = Query(..., max_length=MAX_TEXT), algo: str = "sha256"):
    if algo not in HASH_ALGOS:
        raise HTTPException(400, f"algo must be one of {sorted(HASH_ALGOS)}")
    return {"algo": algo, "hash": hashlib.new(algo, text.encode()).hexdigest()}


@app.get("/api/base64")
def base64_text(text: str = Query(..., max_length=MAX_TEXT), mode: str = "encode"):
    if mode == "encode":
        return {"result": base64.b64encode(text.encode()).decode()}
    if mode == "decode":
        try:
            return {"result": base64.b64decode(text, validate=True).decode()}
        except (binascii.Error, UnicodeDecodeError):
            raise HTTPException(400, "input is not valid base64 text") from None
    raise HTTPException(400, "mode must be 'encode' or 'decode'")


@app.get("/api/url")
def url_text(text: str = Query(..., max_length=MAX_TEXT), mode: str = "encode"):
    if mode == "encode":
        return {"result": quote(text, safe="")}
    if mode == "decode":
        return {"result": unquote(text)}
    raise HTTPException(400, "mode must be 'encode' or 'decode'")


@app.post("/api/json")
def json_format(body: JsonIn):
    try:
        parsed = json.loads(body.text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            400, f"invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})"
        ) from None
    return {"valid": True, "pretty": json.dumps(parsed, indent=2, sort_keys=False)}


def _b64url_json(segment: str) -> dict:
    padded = segment + "=" * (-len(segment) % 4)
    try:
        value = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(400, "token segment is not valid base64url JSON") from None
    if not isinstance(value, dict):
        raise HTTPException(400, "token segment is not a JSON object")
    return value


@app.post("/api/jwt/decode")
def jwt_decode(body: JwtIn):
    """Decode only. The signature is NOT verified; never trust these claims."""
    parts = body.token.strip().split(".")
    if len(parts) != 3:
        raise HTTPException(400, "a JWT has three dot-separated segments")
    payload = _b64url_json(parts[1])
    result = {
        "header": _b64url_json(parts[0]),
        "payload": payload,
        "verified": False,
    }
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        result["expired"] = exp < time.time()
    return result


@app.get("/api/token")
def new_token(kind: str = "urlsafe", length: int = Query(32, ge=8, le=128)):
    if kind == "urlsafe":
        return {"token": secrets.token_urlsafe(length)[:length]}
    if kind == "hex":
        return {"token": secrets.token_hex(length)[:length]}
    if kind == "password":
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
        return {"token": "".join(secrets.choice(alphabet) for _ in range(length))}
    raise HTTPException(400, "kind must be one of ['hex', 'password', 'urlsafe']")


# --------------------------------------------------------------------------
# Optional downstream dependency
# --------------------------------------------------------------------------
if UPSTREAM_URL:

    @app.get("/greet")
    def greet():
        try:
            r = httpx.get(f"{UPSTREAM_URL}/greet", timeout=5.0)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            raise HTTPException(502, "upstream service unavailable") from None


# --------------------------------------------------------------------------
# Fault injection (off by default; prefer mesh-level faults in real clusters)
# --------------------------------------------------------------------------
if CHAOS_ENABLED:
    import random

    log.warning("CHAOS_ENABLED=true: /_chaos/* endpoints are exposed")

    @app.get("/_chaos/slow", include_in_schema=False)
    def chaos_slow():
        delay = random.choice([0.05, 0.1, 0.3, 0.8, 1.5])
        time.sleep(delay)
        return {"delayed_seconds": delay}

    @app.get("/_chaos/error", include_in_schema=False)
    def chaos_error():
        if random.random() < 0.3:
            return JSONResponse({"error": "simulated failure"}, status_code=500)
        return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))