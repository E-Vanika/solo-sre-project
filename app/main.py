"""
Devkit - small, stateless developer utilities behind one API.
"""
import base64
import binascii
import hashlib
import random
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

trace.set_tracer_provider(
    TracerProvider(resource=Resource.create({"service.name": "devkit"}))
)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
tracer = trace.get_tracer(__name__)

app = FastAPI(title="devkit")
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()

REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["path", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["path"])

START_TIME = time.time()
HASH_ALGOS = {"md5", "sha1", "sha256", "sha512"}
MAX_TEXT = 10_000


@app.middleware("http")
async def record_metrics(request: Request, call_next):
    start = time.time()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        if path not in ("/metrics", "/health"):
            REQUEST_COUNT.labels(path=path, status=str(status)).inc()
            REQUEST_LATENCY.labels(path=path).observe(time.time() - start)


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
  main { max-width:760px; margin:0 auto; padding:56px 20px 40px; }
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
  <div class="grid">
    <section class="card"><h2>UUID</h2><p>Generate a random v4 UUID.</p>
      <button onclick="run('/api/uuid','o1')">Generate</button><pre id="o1"></pre></section>
    <section class="card"><h2>Hash</h2><p>Hash text with a common algorithm.</p>
      <input id="h_text" placeholder="Text to hash">
      <div class="row"><select id="h_algo"><option>sha256</option><option>sha512</option>
        <option>sha1</option><option>md5</option></select>
      <button onclick="run('/api/hash?text='+enc('h_text')+'&algo='+val('h_algo'),'o2')">Hash</button></div>
      <pre id="o2"></pre></section>
    <section class="card"><h2>Base64</h2><p>Encode or decode text.</p>
      <input id="b_text" placeholder="Text">
      <div class="row"><select id="b_mode"><option>encode</option><option>decode</option></select>
      <button onclick="run('/api/base64?text='+enc('b_text')+'&mode='+val('b_mode'),'o3')">Run</button></div>
      <pre id="o3"></pre></section>
    <section class="card"><h2>Your IP</h2><p>The address your request came from.</p>
      <button onclick="run('/api/ip','o4')">Show</button><pre id="o4"></pre></section>
    <section class="card"><h2>Unix time</h2><p>Current epoch seconds and ISO 8601.</p>
      <button onclick="run('/api/time','o5')">Show</button><pre id="o5"></pre></section>
  </div>
  <footer>
    <a href="/status">Status</a> &middot;
    <a href="https://github.com/E-Vanika/cloud-playground">Source</a>
  </footer>
</main>
<script>
  function val(id){ return document.getElementById(id).value; }
  function enc(id){ return encodeURIComponent(val(id)); }
  async function run(url, out){
    const el = document.getElementById(out);
    el.textContent = '...';
    try {
      const r = await fetch(url);
      const t = await r.text();
      try { el.textContent = JSON.stringify(JSON.parse(t), null, 2); }
      catch (e) { el.textContent = t; }
    } catch (e) { el.textContent = 'Request failed'; }
  }
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def root():
    return LANDING_PAGE


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/status")
def status():
    return {"status": "ok", "uptime_seconds": int(time.time() - START_TIME)}


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
    forwarded = request.headers.get("x-forwarded-for", "")
    fallback = request.client.host if request.client else "unknown"
    return {"ip": forwarded.split(",")[0].strip() or fallback}


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
            raise HTTPException(400, "input is not valid base64 text")
    raise HTTPException(400, "mode must be 'encode' or 'decode'")


@app.get("/greet")
def greet():
    with tracer.start_as_current_span("call-greeting-service"):
        try:
            r = httpx.get("http://greeting-service:8001/greet", timeout=5.0)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            raise HTTPException(502, "upstream service unavailable")


@app.get("/_chaos/slow")
def chaos_slow():
    delay = random.choice([0.05, 0.1, 0.3, 0.8, 1.5])
    time.sleep(delay)
    return {"delayed_seconds": delay}


@app.get("/_chaos/error")
def chaos_error():
    if random.random() < 0.3:
        return Response(
            content='{"error": "simulated failure"}',
            status_code=500,
            media_type="application/json",
        )
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)