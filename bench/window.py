#!/usr/bin/env python3
"""E05 F2 — one fault window: pick next (fault, telemetry) cell, drive 1 rps synthetic traffic,
inject for FAULT_S seconds, record MTTD (first firing bench alert), MTTR (alert resolved after
clear), success rate under fault. Appends the uniform runs.jsonl record."""
import json, os, subprocess, sys, threading, time, urllib.request
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__)); SVC = "http://127.0.0.1:8019"; PROM = "http://127.0.0.1:9090"
FAULTS = ["retriever_timeout", "llm_timeout", "malformed_llm", "latency_800", "dep_500", "cache_fail", "partial", "dup_storm"]
FAULT_S = int(os.environ.get("FAULT_S", 300)); MAX_WAIT = int(os.environ.get("MAX_WAIT", 240))

def http(url, data=None, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, method="POST" if data is not None else "GET",
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
    except Exception: return 0, b""

def firing():
    _, b = http(PROM + "/api/v1/alerts")
    return sorted({a["labels"]["alertname"] for a in json.loads(b or b'{"data":{"alerts":[]}}')["data"]["alerts"]
                   if a["labels"].get("severity") == "bench" and a["state"] == "firing"})

cell = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"fault": "retriever_timeout", "telemetry": "baseline"}
fault, tel = cell["fault"], cell["telemetry"]
if http(SVC + "/health")[0] != 200: print(json.dumps({"skipped": "faultsvc down"})); sys.exit(0)

http(SVC + "/bench/telemetry", {"level": tel}); http(SVC + "/bench/fault", {"fault": None})
stop = threading.Event(); hits = {"ok": 0, "err": 0, "partial": 0}
def traffic():
    while not stop.is_set():
        s, b = http(SVC + "/query", {"q": "bench"}, timeout=8)
        if s == 200:
            hits["ok"] += 1; hits["partial"] += 1 if b'"partial": true' in b else 0
        else: hits["err"] += 1
        time.sleep(1)
th = threading.Thread(target=traffic, daemon=True); th.start()
time.sleep(45)  # warm-up so rate() windows have data and no stale alert is firing
assert not firing(), f"bench alert already firing before inject: {firing()}"
hits.update(ok=0, err=0, partial=0)

t_inject = time.time(); first = None
try:
    http(SVC + "/bench/fault", {"fault": fault})
    while time.time() - t_inject < FAULT_S:
        if first is None and (a := firing()): first = (time.time(), a)
        time.sleep(5)
finally:
    under = dict(hits); http(SVC + "/bench/fault", {"fault": None})   # never leave a fault on
t_clear = time.time(); resolved = None
while time.time() - t_clear < MAX_WAIT:
    if not firing(): resolved = time.time(); break
    time.sleep(5)
stop.set()
tot = under["ok"] + under["err"]
print(json.dumps({"mttd_s": round(first[0] - t_inject, 1) if first else None, "detected_by": first[1] if first else [],
                  "mttr_s": round(resolved - t_clear, 1) if resolved else None,
                  "success_rate": round(under["ok"] / tot, 3) if tot else None,
                  "partial_rate": round(under["partial"] / tot, 3) if tot else None, "requests": tot}))
