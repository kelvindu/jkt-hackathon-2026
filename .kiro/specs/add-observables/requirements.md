# Requirements Document

## Introduction
The `faulty-workload` service was originally built in the separate `poc` repository under the `cloudwatch-poc` workflow (`../poc/.kiro/specs/cloudwatch-poc`). This feature shall (a) bring that base `faulty-workload` service into this repository as the foundation, and (b) run three additional variant pods on EKS/EC2 on top of it: `customers`, `orders`, and `auth`. Each variant reuses the same fault-injection architecture (FastAPI + structured JSON logging + Prometheus metrics + trace propagation) but exposes a domain-themed fault profile. The base service and all three variants are purely observable targets — they exist to generate telemetry for the analyzer/POC pipeline, not to serve real business traffic.

Because the base service is ported in rather than already present, Requirement 0 below establishes it explicitly so its telemetry contract — inherited from the `cloudwatch-poc` functional requirements — is locked before the variants extend it.

## Glossary
- **Faulty workload**: A synthetic Kubernetes workload that emits controlled failures and anomalies for POC validation.
- **Base faulty-workload**: The original `faulty-workload` service ported from the `poc` repo's `cloudwatch-poc` workflow; runs with `WORKLOAD_FAMILY=default` and defines the telemetry contract the variants inherit.
- **Workload variant**: A configuration-driven instance of the faulty-workload service with a domain-specific fault profile (e.g. customers, orders, auth).
- **Fault profile**: The set of fault-injection parameters (HTTP-500 probability, latency-spike probability/duration, timeout interval, memory-pressure threshold) selected by `WORKLOAD_FAMILY` at startup.
- **Trace ID**: A unique identifier propagated across logs, metrics, and traces to correlate telemetry for a single request.
- **Observable target**: A workload whose sole purpose is to emit telemetry consumed by the analyzer pipeline.
- **Customers variant**: A faulty-workload instance themed around customer-service failure patterns.
- **Orders variant**: A faulty-workload instance themed around order-processing failure patterns.
- **Auth variant**: A faulty-workload instance themed around authentication/authorization failure patterns.

## Requirements

### Requirement 0: Base faulty-workload service (ported from cloudwatch-poc)
**User Story:** As a platform engineer, I want the original `faulty-workload` service from the `cloudwatch-poc` workflow available in this repository, so that the three variants have a working base to extend and the POC telemetry contract is established here rather than assumed.

#### Acceptance Criteria
1. WHEN the base service source is added to this repository, THE SYSTEM SHALL port the existing `faulty-workload` implementation (FastAPI `app.py`, fault engine `faults.py`, structured logger `logger.py`, Prometheus `metrics.py`, trace context `context.py`, and `Dockerfile`) from `../poc/faulty-workload` without altering its telemetry contract.
2. WHEN the base service receives a request, THE SYSTEM SHALL apply its fault-injection engine, which generates intermittent warnings, transient HTTP 500 errors, latency spikes, dependency-timeout events, memory-pressure warnings, and bad-payload warnings, each at an env-configurable frequency.
3. WHEN the base service emits a log line, THE SYSTEM SHALL format it as a single-line structured JSON object containing `timestamp`, `service`, `workload_family`, `severity`, `trace_id`, `request_id`, `error_type`, and `message`.
4. WHEN the base service runs, THE SYSTEM SHALL expose the following low-cardinality Prometheus metrics on a `/metrics` endpoint: `request_count_total`, `warning_count_total`, `error_count_total`, `timeout_count_total`, `restart_count_total`, and the `latency_ms` histogram.
5. WHEN a request arrives, THE SYSTEM SHALL read `X-Trace-ID` and `X-Request-ID` headers into request-scoped context, generate a UUID4 for any absent header, propagate both across logs and metrics, and echo both back in the response headers.
6. WHEN the base service is deployed, THE SYSTEM SHALL run from a single Docker image configured via environment variables (`SERVICE_NAME`, `WORKLOAD_FAMILY`, fault-tuning knobs, and Datadog `DD_AGENT_HOST`/`DD_SERVICE`/`DD_ENV`/`DD_VERSION`) so its telemetry is observable in Datadog.
7. WHERE fault parameters are not explicitly set as environment variables, THE SYSTEM SHALL fall back to the `default` fault profile values, and WHERE they are set, the explicit values SHALL take precedence.

### Requirement 1: Customers variant
**User Story:** As a platform engineer, I want a `customers` variant of the faulty-workload that produces customer-service themed failures, so that I can observe and validate one realistic incident pattern as an observable target.

#### Acceptance Criteria
1. WHEN the `customers` variant runs, THE SYSTEM SHALL reuse the base faulty-workload fault-injection architecture (Requirement 0) and emit intermittent warnings, transient errors, and latency spikes themed around customer-service scenarios.
2. WHEN the `customers` variant emits telemetry, THE SYSTEM SHALL include structured JSON fields for timestamp, service name, workload_family, severity, request_id, error_type, message, and trace_id consistent with the base faulty-workload telemetry contract (Requirement 0).
3. WHEN a `customers` request is processed, THE SYSTEM SHALL propagate trace_id across logs, metrics, and traces; IF trace propagation fails, THE SYSTEM SHALL continue processing the request and log the propagation failure.
4. WHEN the `customers` variant is otherwise idle, THE SYSTEM SHALL still produce periodic health signals via Kubernetes readiness/liveness probe traffic to `/`, surfaced as request-count metrics and `FAULT_SAMPLE_RATE`-sampled "health OK" log lines.

### Requirement 2: Orders variant
**User Story:** As a platform engineer, I want an `orders` variant of the faulty-workload that produces order-processing themed failures, so that I can observe and validate a second distinct incident pattern as an observable target.

#### Acceptance Criteria
1. WHEN the `orders` variant runs, THE SYSTEM SHALL reuse the base faulty-workload fault-injection architecture (Requirement 0) and emit intermittent dependency timeouts, processing errors, and latency spikes themed around order-processing scenarios.
2. WHEN the `orders` variant emits telemetry, THE SYSTEM SHALL include structured JSON fields for timestamp, service name, workload_family, severity, request_id, error_type, message, and trace_id consistent with the base faulty-workload telemetry contract (Requirement 0).
3. WHEN an `orders` request is processed, THE SYSTEM SHALL propagate trace_id across logs, metrics, and traces; IF trace propagation fails, THE SYSTEM SHALL continue processing the request and log the propagation failure.
4. WHEN the `orders` variant is otherwise idle, THE SYSTEM SHALL still produce periodic health signals via Kubernetes readiness/liveness probe traffic to `/`, surfaced as request-count metrics and `FAULT_SAMPLE_RATE`-sampled "health OK" log lines.

### Requirement 3: Auth variant
**User Story:** As a platform engineer, I want an `auth` variant of the faulty-workload that produces authentication/authorization themed failures, so that I can observe and validate a third distinct incident pattern as an observable target.

#### Acceptance Criteria
1. WHEN the `auth` variant runs, THE SYSTEM SHALL reuse the base faulty-workload fault-injection architecture (Requirement 0) and emit intermittent authorization failures, token validation errors, and latency spikes with variance in frequency and severity similar to other faulty-workload variants.
2. WHEN the `auth` variant emits telemetry, THE SYSTEM SHALL include structured JSON fields for timestamp, service name, workload_family, severity, request_id, error_type, message, and trace_id consistent with the base faulty-workload telemetry contract (Requirement 0).
3. WHEN an `auth` request is processed, THE SYSTEM SHALL propagate trace_id across logs, metrics, and traces; IF trace propagation fails, THE SYSTEM SHALL continue processing the request and log the propagation failure.
4. WHEN the `auth` variant is otherwise idle, THE SYSTEM SHALL still produce periodic health signals via Kubernetes readiness/liveness probe traffic to `/`, surfaced as request-count metrics and `FAULT_SAMPLE_RATE`-sampled "health OK" log lines.

### Requirement 4: Variant separation
**User Story:** As a platform engineer, I want each workload variant to remain distinguishable in telemetry, so that I can compare incidents across observable targets without ambiguity.

#### Acceptance Criteria
1. WHEN telemetry is emitted by any variant, THE SYSTEM SHALL preserve workload_family as a searchable dimension.
2. WHEN a single incident affects one variant, THE SYSTEM SHALL not require unrelated variants to be involved in the analysis.
3. WHEN more than one variant fails at once, THE SYSTEM SHALL allow the incidents to be correlated by shared trace or time window.

### Requirement 5: Shared telemetry contract
**User Story:** As a platform engineer, I want all three variants to follow the same telemetry contract as the existing faulty-workload, so that the POC remains consistent and analyzable by the same pipeline.

#### Acceptance Criteria
1. WHEN any variant emits a log line, THE SYSTEM SHALL format it as structured JSON using the same logger module as the existing faulty-workload.
2. WHEN any variant emits a metric, THE SYSTEM SHALL keep the metric names and labels low-cardinality and expose them via the same Prometheus endpoint pattern.
3. WHEN any variant emits traces, THE SYSTEM SHALL preserve trace_id across request boundaries where applicable.
4. WHEN any variant emits an error, THE SYSTEM SHALL include a stable error_type value.

### Requirement 6: Configuration and deployment
**User Story:** As a platform engineer, I want each variant to be deployable as a separate pod using the same Docker image with environment-based configuration, so that I can run all three observable targets without maintaining separate codebases.

#### Acceptance Criteria
1. WHEN a variant is deployed, THE SYSTEM SHALL differentiate behavior through environment variables (e.g. WORKLOAD_FAMILY) rather than separate source trees.
2. WHEN the workloads are configured, THE SYSTEM SHALL allow failure frequency to be adjusted per variant via environment variables.
3. WHEN running locally via `.env`/`docker-compose`, THE SYSTEM SHALL allow the healthy-request log volume to be tuned through `FAULT_SAMPLE_RATE` so idle health-signal noise stays within POC cost limits.
4. WHEN deployed to Kubernetes, THE SYSTEM SHALL emit periodic health signals through readiness/liveness probe traffic to `/`, with the cadence set by each probe's `periodSeconds`, so every variant remains visibly healthy even with no business traffic.
5. WHEN the variants are built, THE SYSTEM SHALL reuse the same Docker image as the base faulty-workload (Requirement 0) rather than maintaining a separate image or source tree per variant.
