# Implementation Plan: add-observables

## Overview

This plan ports the proven `faulty-workload` FastAPI service from `../poc/faulty-workload` into a new `faulty-workload/` directory in this repository, confirms the fault-profile registry covers the `default`, `customers`, `orders`, and `auth` families, and adds the deployment artifacts (single Dockerfile, `docker-compose`, per-variant Kubernetes manifests) that launch all four families from one image via `WORKLOAD_FAMILY`.

The telemetry contract (structured JSON logs, low-cardinality Prometheus metrics, trace/request-ID propagation) is locked by Requirement 0 and ported unchanged. Tasks are ordered bottom-up: leaf modules with no internal dependencies first (`context`, `logger`, `metrics`), then the configuration and fault layers (`profiles`, `faults`), then the `app.py` entrypoint that wires everything together, and finally the deployment artifacts. The five correctness properties from the design are written as Hypothesis property-based tests placed next to the code they validate; example, smoke, and integration tests cover the fixed instrument set, deployment wiring, and edge paths.

Implementation language: **Python** (FastAPI + Hypothesis), as specified in the design.

## Tasks

- [ ] 1. Port foundational telemetry modules (no internal dependencies)
  - [ ] 1.1 Port `context.py` and create `requirements.txt`
    - Create `faulty-workload/context.py` with `trace_id_var` / `request_id_var` `ContextVar`s (default `""`) and `get_trace_id()` / `get_request_id()` accessors
    - Create `faulty-workload/requirements.txt` pinning `fastapi`, `uvicorn`, `prometheus-client`, `python-dotenv`, `ddtrace`, `boto3` (and `hypothesis` for tests)
    - Port verbatim from `../poc/faulty-workload` without altering behavior
    - _Requirements: 0.1, 0.5_

  - [ ] 1.2 Port `logger.py` structured JSON logger
    - Create `faulty-workload/logger.py` with `JsonFormatter(service_name)` emitting a single-line JSON object containing `timestamp` (ISO-8601 UTC), `service`, `workload_family`, `severity`, `trace_id`, `request_id`, `error_type`, `message`
    - Resolve `trace_id` / `request_id` from record `extra` first, then `context.py` contextvars, then `""`
    - Provide idempotent `get_logger(service_name)` writing to stdout with `propagate=False`
    - _Requirements: 0.1, 0.3, 5.1, 5.4_

  - [ ]* 1.3 Write property test for log formatting
    - **Property 2: Log lines are single-line JSON carrying the full telemetry contract**
    - Generate random log records (arbitrary severity, message, `trace_id`, `request_id`, `error_type`) under arbitrary `workload_family`; assert no embedded newline, parses as one JSON object, includes all eight required fields, with `workload_family` equal to the configured family and `error_type` equal to the supplied label (or `""` when none)
    - Hypothesis, minimum 100 iterations; tag: `# Feature: add-observables, Property 2`
    - **Validates: Requirements 0.3, 1.2, 2.2, 3.2, 4.1, 5.1, 5.4**

  - [ ] 1.4 Port `metrics.py` Prometheus instruments
    - Create `faulty-workload/metrics.py` with counters `request_count_total{workload_family}`, `warning_count_total{workload_family,warning_type}`, `error_count_total{workload_family}`, `timeout_count_total{workload_family}`, `restart_count_total`, and histogram `latency_ms{workload_family}` with fixed buckets
    - Expose `metrics_app = make_asgi_app()` for mounting at `/metrics`
    - _Requirements: 0.4, 5.2_

  - [ ]* 1.5 Write unit test for the metric instrument set
    - Assert `/metrics` exposes exactly the expected instruments and only low-cardinality labels (`workload_family`, `warning_type`); assert no `trace_id` / `request_id` labels exist
    - _Requirements: 0.4, 5.2_

- [ ] 2. Port configuration and fault-injection layers
  - [ ] 2.1 Port `profiles.py` registry and confirm family coverage
    - Create `faulty-workload/profiles.py` with `PROFILES` containing entries for `default`, `customers`, `orders`, and `auth` matching the design's fault-profile table (HTTP-500 prob, latency-spike prob/min/max, timeout interval, memory-pressure threshold)
    - Implement `get_profile(family) -> dict[str, str]` returning the family dict, falling back to `default` for unknown families
    - _Requirements: 0.7, 1.1, 2.1, 3.1, 6.1, 6.2_

  - [ ] 2.2 Port `faults.py` fault-injection engine
    - Create `faulty-workload/faults.py` with `FaultResult` dataclass and `apply_faults(request)` that increments a lock-protected global counter then runs `_maybe_http_500`, `_maybe_latency_spike`, `_maybe_timeout`, `_maybe_memory_pressure`, `_maybe_bad_payload`
    - Read all thresholds/probabilities from env once at import time; raise `HTTPException(500)` on the hard-fault draw; return warning-class `FaultResult`s otherwise
    - _Requirements: 0.2_

  - [ ]* 2.3 Write property test for deterministic periodic faults
    - **Property 4: Deterministic periodic faults fire exactly on their configured interval**
    - Generate random positive interval `N` and counter value `c`; assert dependency-timeout fires iff `c % N == 0` and memory-pressure fires iff `c % MEMORY_PRESSURE_THRESHOLD == 0`; assert non-positive intervals never fire
    - Hypothesis, minimum 100 iterations; tag: `# Feature: add-observables, Property 4`
    - **Validates: Requirements 0.2**

- [ ] 3. Checkpoint - foundational and fault layers
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Port and wire the `app.py` entrypoint
  - [ ] 4.1 Port `app.py` HTTP surface, middleware, and startup resolution
    - Create `faulty-workload/app.py` with `TraceContextMiddleware` (reads `X-Trace-ID`/`X-Request-ID`, generates UUID4 when absent, stores both in contextvars, echoes both into response headers)
    - Implement `GET /` handler: increment `request_count`, call `apply_faults`, record `latency_ms`, increment `error_count`/`warning_count`/`timeout_count` as appropriate, emit `FAULT_SAMPLE_RATE`-sampled "Health check OK" info log, return `{"status":"ok", "service":..., "warnings"?:[...]}`
    - Mount `metrics_app` at `/metrics`
    - Implement startup block: resolve `WORKLOAD_FAMILY`, apply profile via `os.environ.setdefault` per key **before** importing `faults.py`, and compute `_FAULT_SAMPLE_RATE` clamped to `[0.0, 1.0]`
    - _Requirements: 0.2, 0.4, 0.5, 0.6, 0.7, 1.1, 1.3, 1.4, 2.1, 2.3, 2.4, 3.1, 3.3, 3.4, 6.1, 6.2, 6.3_

  - [ ]* 4.2 Write property test for profile resolution precedence
    - **Property 1: Profile resolution honors explicit overrides and fills defaults**
    - Generate random `WORKLOAD_FAMILY` (known or unknown) plus a random subset of pre-set fault-parameter env vars; run the `setdefault` resolution; assert every pre-set key keeps its explicit value and every unset key equals `get_profile(family)` (unknown → `default`)
    - Hypothesis, minimum 100 iterations; tag: `# Feature: add-observables, Property 1`
    - **Validates: Requirements 0.7, 1.1, 2.1, 3.1, 6.1, 6.2**

  - [ ]* 4.3 Write property test for trace/request ID propagation
    - **Property 3: Trace and request IDs are always present, echoed, or validly generated**
    - Drive the app with `TestClient` over all present/absent combinations of `X-Trace-ID` / `X-Request-ID`; assert both headers appear on the response, supplied values are echoed unchanged, absent values are valid UUID4, and resolved values match those exposed to logging via the request context
    - Hypothesis, minimum 100 iterations; tag: `# Feature: add-observables, Property 3`
    - **Validates: Requirements 0.5, 1.3, 2.3, 3.3, 5.3**

  - [ ]* 4.4 Write property test for sample-rate clamping
    - **Property 5: Sample rate is always clamped to a valid probability**
    - Generate arbitrary float inputs for `FAULT_SAMPLE_RATE`; assert the resolved rate lies within `[0.0, 1.0]` and equals the input when already in range
    - Hypothesis, minimum 100 iterations; tag: `# Feature: add-observables, Property 5`
    - **Validates: Requirements 6.3, 1.4, 2.4, 3.4**

  - [ ]* 4.5 Write example/unit tests for handler edge paths
    - Health happy path: `GET /` returns `{"status":"ok"}`, increments `request_count`, emits a sampled info log (Req 1.4/2.4/3.4)
    - Trace-propagation failure path: inject a context error and assert the request still returns 200 and a propagation-failure line is logged (Req 1.3/2.3/3.3)
    - _Requirements: 1.3, 1.4, 2.3, 2.4, 3.3, 3.4_

- [ ] 5. Checkpoint - service runs end-to-end from env config
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Port the Dockerfile and verify single-image startup
  - [ ] 6.1 Port `Dockerfile` (single image for all families)
    - Create `faulty-workload/Dockerfile` installing `requirements.txt` with `CMD uvicorn app:app --host 0.0.0.0 --port 8080`
    - Configure entirely via environment variables (`SERVICE_NAME`, `WORKLOAD_FAMILY`, fault knobs, `DD_AGENT_HOST`/`DD_SERVICE`/`DD_ENV`/`DD_VERSION`)
    - _Requirements: 0.1, 0.6, 6.1, 6.5_

  - [ ]* 6.2 Write smoke test for ported modules and env-only startup
    - Assert all ported modules import cleanly and expose expected public symbols (`apply_faults`, `get_profile`, `get_logger`, `metrics_app`, contextvar accessors) (Req 0.1)
    - Assert the app starts from env-only configuration with no code changes between families (Req 0.6)
    - _Requirements: 0.1, 0.6_

- [ ] 7. Author the docker-compose stack for all four families
  - [ ] 7.1 Create `docker-compose.yml` with base + three variant services and Datadog Agent
    - Single shared `build` context; services for `default` (base), `customers`, `orders`, `auth` differentiated only by `WORKLOAD_FAMILY`/`SERVICE_NAME` env, mapped to host ports 8080–8083 with `FAULT_SAMPLE_RATE=1.0`
    - Datadog Agent container collecting container logs and scraping each variant's `/metrics` via `DD_PROMETHEUS_SCRAPE_CHECKS`
    - _Requirements: 4.1, 6.1, 6.2, 6.3, 6.5_

  - [ ]* 7.2 Write smoke test asserting single shared image across compose services
    - Parse `docker-compose.yml`; assert all four family services reference the single `faulty-workload` build context/image rather than per-variant images (Req 6.5)
    - _Requirements: 6.5_

- [ ] 8. Author Kubernetes manifests per variant
  - [ ] 8.1 Create per-variant `Deployment` + `Service` manifests
    - One `Deployment` + `Service` each for `customers`, `orders`, `auth`, all referencing `image: faulty-workload:latest`
    - Env block per variant: `SERVICE_NAME`, `WORKLOAD_FAMILY`, `DD_SERVICE`/`DD_ENV`/`DD_VERSION`, `DD_AGENT_HOST` from `status.hostIP`, `FAULT_SAMPLE_RATE`
    - Readiness/liveness probes on `/` with a `periodSeconds` cadence to provide the idle health signal
    - _Requirements: 1.4, 2.4, 3.4, 4.2, 4.3, 6.1, 6.4, 6.5_

  - [ ]* 8.2 Write smoke tests for manifest wiring
    - Assert every variant Deployment references the single `faulty-workload` image (Req 6.5)
    - Assert each Deployment defines readiness/liveness probes on `/` with a `periodSeconds` cadence (Req 6.4)
    - Assert separate Deployments/Services keep `workload_family` distinct so single-variant incidents stay isolated (Req 4.2, 4.3)
    - _Requirements: 4.2, 4.3, 6.4, 6.5_

- [ ] 9. Integration verification of the running stack
  - [ ]* 9.1 Write docker-compose integration test for telemetry collection
    - Bring up the compose stack with the Datadog Agent; confirm each variant's logs are collected and each `/metrics` endpoint is scraped, with `workload_family` distinguishing the streams (1–3 representative runs, not property-based)
    - _Requirements: 4.1, 5.2_

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirement sub-clauses for traceability.
- Property tests carry the universal guarantees (config precedence, log schema, ID propagation, fault periodicity, clamping); example, smoke, and integration tests cover the fixed instrument set, deployment wiring, and edge paths that do not vary with input.
- Property tests are placed next to the code they validate so regressions surface early; each is tagged `# Feature: add-observables, Property {number}` and runs a minimum of 100 Hypothesis iterations.
- The `default`, `customers`, `orders`, and `auth` profiles all share one source tree and one image, differentiated only by `WORKLOAD_FAMILY`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.4", "2.1"] },
    { "id": 1, "tasks": ["1.3", "1.5", "2.2", "6.1"] },
    { "id": 2, "tasks": ["2.3", "4.1"] },
    { "id": 3, "tasks": ["4.2", "4.3", "4.4", "4.5", "6.2", "7.1", "8.1"] },
    { "id": 4, "tasks": ["7.2", "8.2", "9.1"] }
  ]
}
```
