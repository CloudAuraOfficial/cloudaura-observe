# E05 fault-injection target: a mock RAG request path (cache → retriever → llm) with
# runtime-switchable faults and two telemetry levels. Bench-only; never serves real traffic.
import asyncio, json, logging, os, random, sys, time, uuid
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

FAULTS = ["retriever_timeout", "llm_timeout", "malformed_llm", "latency_800", "dep_500", "cache_fail", "partial", "dup_storm"]
state = {"fault": None, "telemetry": os.environ.get("TELEMETRY", "baseline")}  # baseline | enriched
SERVICE = os.environ.get("SERVICE_NAME", "faultsvc")

# Baseline telemetry: the two symptom metrics every service already has.
REQS = Counter("http_requests_total", "requests", ["service", "status"])
DUR = Histogram("http_request_duration_seconds", "latency", ["service"])
# Enriched telemetry: names the failing component. Only emitted when telemetry=enriched.
STAGE_ERR = Counter("stage_errors_total", "stage failures", ["service", "stage", "kind"])
RETRIES = Counter("stage_retries_total", "retries", ["service", "stage"])
FAULT_G = Gauge("bench_fault_active", "1 while a fault is injected", ["service", "fault"])

log = logging.getLogger("faultsvc"); log.addHandler(logging.StreamHandler(sys.stdout)); log.setLevel(logging.INFO)
def jlog(**kv): log.info(json.dumps(kv))
app = FastAPI()

class StageError(Exception):
    def __init__(self, stage, kind, status=500): self.stage, self.kind, self.status = stage, kind, status

async def stage(name, base_ms, rid, ctx):
    f = state["fault"]
    if name == "cache" and f == "cache_fail": raise StageError("cache", "unavailable", 503)
    if name == "retriever" and f == "retriever_timeout": await asyncio.sleep(3); raise StageError("retriever", "timeout", 504)
    if name == "retriever" and f == "dep_500": raise StageError("retriever", "dependency_500", 502)
    if name == "llm" and f == "llm_timeout": await asyncio.sleep(3); raise StageError("llm", "timeout", 504)
    if name == "llm" and f == "malformed_llm": raise StageError("llm", "malformed_response", 502)
    if name == "llm" and f == "partial": ctx["partial"] = True
    await asyncio.sleep((base_ms + (800 if f == "latency_800" else 0)) / 1000)

@app.post("/query")
async def query(req: Request):
    rid = req.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    ctx = {"request_id": rid, "model": "mock-llm-v1", "prompt_version": "p3", "retrieval_version": "r2", "retry_count": 0}
    t0 = time.perf_counter(); status = 200
    try:
        for name, ms in (("cache", 5), ("retriever", 60), ("llm", 250)):
            for attempt in range(2):  # one retry per stage
                try: await stage(name, ms, rid, ctx); break
                except StageError as e:
                    if attempt == 0 and e.kind != "timeout":
                        ctx["retry_count"] += 1
                        if state["telemetry"] == "enriched": RETRIES.labels(SERVICE, name).inc()
                        continue
                    raise
        body = {"answer": "mock", "request_id": rid, "partial": ctx.get("partial", False)}
    except StageError as e:
        status = e.status; body = {"error": e.kind, "message": f"{e.stage} failed", "statusCode": status}
        if state["telemetry"] == "enriched": STAGE_ERR.labels(SERVICE, e.stage, e.kind).inc()
        ctx["dependency"] = e.stage
    dur = time.perf_counter() - t0
    REQS.labels(SERVICE, str(status)).inc(); DUR.labels(SERVICE).observe(dur)
    if state["telemetry"] == "enriched": jlog(level="info" if status < 500 else "error", status=status, duration_ms=round(dur * 1000), **ctx)
    else: jlog(level="info" if status < 500 else "error", status=status, duration_ms=round(dur * 1000))
    if state["fault"] == "dup_storm" and random.random() < 0.5:  # client-side storm: every request fans to 5 dupes
        await asyncio.gather(*(stage("llm", 250, rid, {}) for _ in range(4)))
    return Response(json.dumps(body), status_code=status, media_type="application/json")

@app.post("/bench/fault")
async def set_fault(req: Request):
    if os.environ.get("BENCH_FAULTS_ENABLED") != "1": return Response('{"error":"disabled"}', 403)
    f = (await req.json()).get("fault")
    if f not in FAULTS and f is not None: return Response('{"error":"unknown fault"}', 400)
    for x in FAULTS: FAULT_G.labels(SERVICE, x).set(1 if x == f else 0)
    state["fault"] = f; jlog(event="fault_set", fault=f); return {"fault": f}

@app.post("/bench/telemetry")
async def set_tel(req: Request):
    lvl = (await req.json()).get("level")
    if lvl not in ("baseline", "enriched"): return Response('{"error":"baseline|enriched"}', 400)
    state["telemetry"] = lvl; return state

@app.get("/health")
async def health(): return {"ok": True, **state}
@app.get("/metrics")
async def metrics(): return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
