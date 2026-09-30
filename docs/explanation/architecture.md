# Explanation: how the walking skeleton implements the v4.0 plan

The full plan is in [implementation-plan-v4.md](implementation-plan-v4.md). This page maps the plan
to the code and states plainly what is not yet implemented.

## Layers (spec 4.1, ADR 0001)

```text
hop/platform/                         domain-agnostic core
  common_contracts/  Pydantic v2 contracts, JSON Schemas in docs/reference/schemas, missingness (8.4)
  workflow_runtime/  idempotent, checkpointed runs; retries, timeouts, budgets, kill switch, dead letters
  model_gateway/     governed model calls: mock (default) and OpenAI-compatible adapters
  evidence_service/  immutable, versioned evidence; raw payloads in a write-once object store; lineage
  capability_registry/ YAML manifests: owner, status, tools, egress, limits, SLO
  policy_engine/     deny-by-default tools, egress allowlist and SSRF guard, RBAC, budgets, injection scan
  evaluation/        golden-set harness and quality ratchet
  observability/     OpenTelemetry spans stored per trace; cost records
  api/               FastAPI base app: header identity, traceparent, platform routes
  storage/ audit/ integrations/ entity_resolution/ domain_registry/ analytics/
hop/products/opportunity_intelligence/
  collection, normalisation, metrics, gap_detection (rules and gates), counter_evidence, scoring,
  opportunity_lifecycle (cards, review, export), evaluation, api, dashboard
domain_packs/sports_footwear/         markets, taxonomy, brands, attributes, prompts, rules, scoring,
                                      evaluation_sets, sandbox fixtures
hop/bootstrap.py                      composition root; hop/cli, hop/api.py and the dashboard use it
```

## Workflow (spec 7)

| # | Activity | Span | What it guarantees |
|---|---|---|---|
| 1 | `validate_config` | Configuration validation | Pack schema, rule tests and every capability must be executable before any spend |
| 2 | `estimate_cost` | Cost estimation | The estimate must fit the tier budget; larger budgets need a named approver |
| 3–5 | `collect_demand`, `collect_serp`, `collect_gerp` | … collection | Raw payloads are hashed and stored. Each observation carries its state (OBSERVED, NOT_COLLECTED, PROVIDER_ERROR, …) |
| 6 | `normalise` | Normalisation | Evidence items reference the payload URI and hash. Injection-flagged SERP content is quarantined |
| 7 | `resolve_entities` | Entity resolution | Alias registry plus context rules. Ambiguous surfaces such as "On" stay ambiguous |
| 8 | `data_quality` | Data-quality checks | Coverage per need and family. A critical failure blocks admission |
| 9 | `compute_metrics` | Metrics | Wilson intervals, `exploratory` when n < 30, HHI; missing stays missing |
| 10 | `gap_detection` | Gap detection | Three-valued rule evaluation. A bounded retrieval agent collects the supporting evidence |
| 11 | `counter_evidence` | Counter-evidence | Family-specific searches for evidence against each gap, graded by strength |
| 12 | `admission_gates` | Admission gates | The ten gates of spec 7.1 (critical ones: lineage, data quality, untrusted content) |
| 13 | `scoring` | Scoring | Deterministic score (9.5) with penalties and sensitivity |
| 14 | `create_cards` | Opportunity Card creation | Draft cards with evidence-linked statements and a validated explanation |
| 15 | `evaluation` | Evaluation | Run-level release checks: evidence exists, no quarantined support, explanation validated, audit chain intact |

## Human accountability (spec 3.3, 12.5)

Cards move only through `Draft → In Review → Approved / Watchlist / Rejected`, with Reopen. Every
transition is RBAC-checked, needs a named reviewer, and is stored as a `ReviewDecision` and a
hash-chained audit event.

- Approval needs an accountable owner.
- Reject, Watchlist and Reopen need a rationale.
- HIGH priority cards need the `review_board` role.
- A denied attempt is audited and leaves the card unchanged.

## Governance

- **Capabilities.** Every agent or collector is a manifest in `hop/platform/capability_registry/manifests/`
  or `hop/products/opportunity_intelligence/capabilities/`. Only `approved` capabilities execute
  anywhere; `tested` ones execute outside production only. `experimental.web_browse` is a `draft`
  manifest kept to show that denial path. Revocation is persisted and takes effect at the next check.
- **Tools.** An `AgentSession` grants only the tools listed in the manifest. It validates arguments
  with Pydantic and stops at `max_steps` or `max_duration_seconds`.
- **Egress.** Only HTTPS to hosts in the manifest allowlist is permitted. IP literals, internal names,
  credentials in URLs and non-443 ports are refused.
- **Untrusted content.** Provider and model text is delimited, scanned for injection patterns, never
  executed, and cannot be used as supporting evidence when flagged. See
  `tests/policy/test_prompt_injection.py`.

## Dashboard (spec 14)

| Page | Highlights |
|---|---|
| Executive Opportunity Portfolio | Ranked cards, priority mix, score versus evidence confidence |
| Consumer Need Explorer | Demand index with coverage; every rate with n and a 95% CI; missing shown as missing |
| SERP Landscape | Supply share, top-3 share, brand visibility, HHI and features per need |
| GERP Recommendation Landscape | Primary, supporting, mention and exclusion labels; recommendation coverage; stability across repeats |
| SERP–GERP Gap Matrix | Rule-by-need outcome heatmap (MATCHED, NOT_MATCHED, UNKNOWN); quadrant chart; RBAC-gated what-if thresholds that never change stored results |
| Opportunity Evidence Room | Statements, score decomposition with sensitivity, gates, evidence and counter-evidence with lineage, review history, Approve / Watchlist / Reject |
| Platform Health & Governance | Runs and traces, costs, capabilities, policy decisions, evaluations, audit chain |

## Not yet implemented (later phases)

| Area | Walking skeleton | Target |
|---|---|---|
| Identity | `X-HOP-User` / `X-HOP-Role` headers, a role selector in the dashboard, and `--user/--role` in the CLI | Microsoft Entra ID (OIDC), group-to-role mapping, workload identity |
| Orchestration | In-process runtime with checkpoints (ADR 0002) | Celery workers on Redis, or Temporal |
| Providers | Sandbox fixtures; DataForSEO adapter tested against a mocked transport | Live DataForSEO calibration, a second SERP provider, multi-provider routing |
| Models | Deterministic mock; OpenAI-compatible adapter with egress and budget controls | Model registry, champion-challenger and shadow runs, held-out golden sets labelled by analysts |
| Telemetry | Spans and costs stored in the database and shown in the CLI and dashboard | OTLP export to a collector with alerting (spec 11.3) |
| Storage | SQLite, or Postgres 16 via `DATABASE_URL` (full suite and sandbox run verified with `make test-postgres`; no migration tool yet); local object store | Managed Postgres, S3-compatible object-lock storage, retention jobs |
| Security | Egress allowlist, RBAC, redaction, injection scanning | Secrets manager, supply-chain scanning, a DLP review of exports |
