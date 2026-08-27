# Observability fault injection: does enriched telemetry move MTTD/MTTR, and which faults stay invisible?

**1 · Question.** For a request pipeline (retrieve → LLM → cache → respond), what does *component-level*
telemetry buy over the symptom-only alerts every service gets for free — and which failure classes
does neither tier see?

**2 · Hypothesis.** Symptom alerts (error-rate, P95) detect hard failures in ~a minute; enriched
telemetry (per-stage error/retry counters + structured request context) detects faster *and names
the failing stage*; some faults produce no symptom and stay invisible to both.

**3 · Setup.** `bench/faultsvc` — a mock pipeline (Flask + prometheus_client, loopback :8019) with 8
env-flippable faults: `retriever_timeout` · `llm_timeout` · `malformed_llm` · `latency_800` ·
`dep_500` · `cache_fail` · `partial` (HTTP 200, truncated answer) · `dup_storm` (client re-sends).
Two telemetry arms: **baseline** = `http_requests_total` + duration histogram only; **enriched** =
baseline + `stage_errors_total{stage,kind}` + `stage_retries_total{stage}` + JSON request log
(`request_id, model, prompt_version, retrieval_version, retry_count`).
Alert rules (`prometheus/alerts.yml`, scoped `service="faultsvc"`, severity `bench`, never route to
the real topic): baseline tier `BenchHighErrorRate` (5xx > 5 %, `for: 30s`) and `BenchHighLatency`
(P95 > 1 s, `for: 30s`); enriched tier `BenchStageFailing` (`for: 15s`) and `BenchRetryStorm`
(`for: 15s`). Prometheus scrape + eval = 15 s, all rules on `rate(…[1m])`.
`bench/window.py` runs one cell per hour (slot :35): 1 rps synthetic traffic, 45 s warm-up, inject
5 min, MTTD = first bench alert firing, clear, MTTR = alert resolved. 16 cells = 8 faults × 2 arms.
Hardware: 4-vCPU VPS; all timings RELATIVE-ONLY and quantised by the 15 s scrape/eval grid.

**4 · Metrics.** MTTD (s), detected-by (which rule), MTTR (s), success-rate under fault, partial-rate.

**5 · Result** (137 windows, 8–9 per cell, 2026-08-20 → 08-27; `results/runs.jsonl`).

| fault | user impact | baseline: MTTD · rule | enriched: MTTD · rule |
|---|---|---|---|
| retriever_timeout | 1 % success | 60 s · ErrorRate+Latency | **45 s · StageFailing{retriever}** |
| llm_timeout | 1 % | 60 s · ErrorRate+Latency | **45 s · StageFailing{llm}** |
| malformed_llm | 0 % | 60 s · ErrorRate | **45 s · StageFailing+RetryStorm** |
| dep_500 | 0 % | 60 s · ErrorRate | **45 s · StageFailing+RetryStorm** |
| cache_fail | 0 % | 60 s · ErrorRate | **45 s · StageFailing+RetryStorm** |
| latency_800 | 100 % success, slow | 60 s · Latency | 60 s · Latency (no stage error → enriched adds nothing) |
| **partial** | 100 % "success", **99.6 % truncated** | **undetected** (9/9) | **undetected** (8/8) |
| **dup_storm** | 100 % success, 2× load | **undetected** (9/9) | **undetected** (8/8) |

Variance: MTTD medians are exact across windows (min = median except three 75 s outliers on baseline
= one scrape late). MTTR = **60 s flat in every detected cell, both arms** — it is the `rate(…[1m])`
window draining, not remediation; nothing in either tier shortens it.

**6 · Trade-off.**
- The 60 → 45 s MTTD gain is **real but mostly configuration**: it equals the `for:` difference
  (30 s vs 15 s) that a stage-scoped rule can afford because it's less noisy than a global error-rate.
  Enriched telemetry's actual purchase is **localisation** — the alert *name* carries the failing
  stage, which is the first 10 minutes of any incident bridge — not raw speed.
- Both tiers share a floor: scrape (15 s) + eval (15 s) + rate window (60 s) + `for:`. Below ~30 s
  MTTD you need push-based signals or a shorter rate window, which raises false positives.
- **Two of eight faults are invisible to any metric-based alert** because they produce HTTP 200:
  `partial` (the AI-product failure — "wrong/truncated answer throws no exception") and `dup_storm`
  (load doubles, nothing errors). Success-rate monitors report 100 % while 99.6 % of answers are
  truncated. These need *quality* telemetry (answer-length/coverage distribution, per-client request
  rate), i.e. a different signal class, not a better threshold.
- Cost of enriched: two extra counters + one JSON log line per request; negligible here, but the
  label cardinality (`stage × kind`) is the thing to budget at scale.

**7 · Decision.** Ship enriched stage counters on every pipeline service (cheap, and the alert names
the component). Keep symptom rules as the safety net. Add a **quality-signal** family for the
200-OK failures: partial/truncation rate and per-client request-rate anomalies — that is the gap
the numbers exposed. Don't chase MTTD below the scrape/eval floor with metrics; use traces or
push events if that matters.

**8 · Interview insight (30 s).** "I fault-injected eight failures into a pipeline under two
telemetry tiers, 137 windows. Symptom alerts caught hard failures in ~60 s; stage-level counters
caught them in ~45 s *and named the stage*. But two faults — truncated 200-OK answers and a
duplicate-request storm — were invisible to both, with success-rate reading 100 %. That's the
AI-product lesson: MTTD for 'wrong answer' needs quality telemetry by design, because nothing
throws."

**9 · Deep-dive rabbit holes.**
- *Isn't 45 vs 60 just your `for:` setting?* Yes, largely — and I'd say so; the stage rule can afford
  a shorter hold because it's scoped. The durable gain is localisation.
- *Why is MTTR flat?* It's the `rate[1m]` window draining after clear; no auto-remediation was in
  scope. Real MTTR is bridge time, where the alert naming the stage is what moves it.
- *How would you catch `partial`?* Answer-length / coverage distribution vs a rolling baseline;
  LLM-judge sampling on a slice; client-side "was this useful" rate. *`dup_storm`?* Per-client
  request-rate + idempotency-key collision rate.
- *Cardinality of `stage × kind`?* Bounded enum here; at scale cap `kind` to a fixed vocabulary.
- *Why 1 rps?* Enough for `rate[1m]` to be stable on a 4-vCPU host without perturbing other
  experiments; the *shape* of the result is rate-independent, the absolute MTTD isn't.

**Levels.** L1: MTTD/MTTR are the incident metrics leadership feels. L2: metrics-based MTTD has a
structural floor = scrape + eval + rate window + hold. L3: stage-scoped alerts trade a little
cardinality for localisation and a shorter hold; 200-OK failures need quality signals, not
thresholds. **L4: "Across 137 injected-fault windows, stage-level telemetry cut MTTD 60 → 45 s and
named the failing stage; two of eight faults — truncated answers and a duplicate storm — were
invisible to every metric alert at 100 % success rate."**

Reproduce: `docker compose -f bench/docker-compose.yml up -d` · `python3 bench/window.py
'{"fault":"partial","telemetry":"enriched"}'` · rules in `prometheus/alerts.yml` (`bench_e05_*`).
