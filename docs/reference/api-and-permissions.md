# Reference: HTTP API, roles and permissions

Start the API with `make api`, or run `uvicorn --factory hop.api:create_app`. Interactive OpenAPI docs
are served at `/docs`.

## Identity

Callers identify themselves with two headers:

- `X-HOP-User`: a name (default `anonymous`);
- `X-HOP-Role`: a role (default `viewer`).

These headers stand in for Microsoft Entra ID tokens and group-to-role mapping (Phase 5). Every
permission check is recorded as a policy decision. Review actions reject anonymous reviewers.

A W3C `traceparent` header on a request is continued, and each response carries a `traceparent`
header.

## Roles

| Permission | viewer | analyst | domain_reviewer | review_board | platform_engineer | admin |
|---|---|---|---|---|---|---|
| `opportunity:read`, `run:read`, `trace:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `evidence:read` | | ✓ | ✓ | ✓ | ✓ | ✓ |
| `evidence:raw_read` | | ✓ | ✓ | ✓ | | ✓ |
| `run:create` | | ✓ | | | ✓ | ✓ |
| `review:submit`, `review:decide` | | ✓ | ✓ | ✓ | | ✓ |
| `review:approve_high_priority` | | | | ✓ | | ✓ |
| `gap_matrix:tune` (what-if sliders) | | ✓ | ✓ | ✓ | | ✓ |
| `evaluation:run` | | ✓ | | | ✓ | ✓ |
| `runtime:kill_switch`, `capability:revoke`, `config:write` | | | | | ✓ | ✓ |

This table is the source of truth in `hop.platform.policy_engine.ROLE_PERMISSIONS`, and
`tests/policy/test_policy_engine.py::test_rbac_matrix` tests it.

## Endpoints

### Platform (`hop.platform.api`)

| Method and path | Permission | Notes |
|---|---|---|
| `GET /health` | none | Environment, database, kill switch, audit chain validity and default model |
| `GET /runs` | `run:read` | |
| `GET /runs/{run_id}` | `run:read` | Includes the per-capability cost breakdown |
| `POST /runs/{run_id}/cancel` | `run:create` | |
| `GET /traces/{trace_id}` | `trace:read` | Span tree and raw spans |
| `GET /evidence/{evidence_id}` | `evidence:read` | Item, version count and lineage check (payload hash and record hash) |
| `GET /evidence/{evidence_id}/raw` | `evidence:raw_read` | Raw provider payload, marked `untrusted_content` |
| `GET /audit` | `run:read` | Hash-chained audit events and chain validity |
| `GET /capabilities` | `run:read` | Manifests with status and revocation state |
| `GET /policy/decisions` | `run:read` | Recent allow and deny decisions |
| `GET /costs` | `run:read` | Cost records, optionally filtered with `?run_id=` |

### Opportunity Intelligence (`hop.products.opportunity_intelligence.api`)

| Method and path | Permission | Notes |
|---|---|---|
| `POST /runs` | `run:create` | Body: `{"market": "HK", "tier": "A", "provider": "auto", "force_new": false, ...}`. Runs synchronously and returns the run and its card ids |
| `POST /runs/estimate` | `run:read` | Cost estimate against the tier budget |
| `GET /opportunities` | `opportunity:read` | Filters: `status`, `market`, `run_id` |
| `GET /opportunities/{card_id}` | `opportunity:read` | Card, allowed actions and review history |
| `GET /opportunities/{card_id}/evidence` | `evidence:read` | Supporting and counter-evidence items |
| `POST /opportunities/{card_id}/review` | `review:submit`, plus `review:decide` and, for HIGH approvals, `review:approve_high_priority` | Body: `{"action": "APPROVE", "owner": "...", "rationale": "..."}`. Returns 403 if not permitted, 422 if a rule is not met, 409 for an invalid transition |
| `GET /opportunities/export?fmt=csv` | `opportunity:read` | Governed export (capability `opportunity.exporter`), written to the object store and audited |
| `GET /candidates?run_id=` | `opportunity:read` | All gap candidates with gate results |

Errors: a `PolicyViolation` returns 403, and an engaged kill switch returns 503.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `HOP_DATA_DIR` | `var/` | Holds the SQLite database and object store |
| `DATABASE_URL` | `sqlite:///$HOP_DATA_DIR/hop.db` | For Postgres use `postgresql+psycopg://user:pw@host/db` (needs the `postgres` extra) |
| `HOP_OBJECT_STORE_DIR` | `$HOP_DATA_DIR/objects` | Local write-once object store |
| `HOP_DOMAIN_PACKS_DIR` | `domain_packs/` | |
| `HOP_DOMAIN_PACK` | `sports-footwear` | Default pack |
| `HOP_ENV` | `sandbox` | `production` refuses to run capabilities with status `tested` |
| `HOP_SERP_PROVIDER` | `auto` | `auto` uses DataForSEO when credentials are set, otherwise the sandbox. Also accepts `sandbox` or `dataforseo` |
| `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | unset | Enable the DataForSEO adapter |
| `HOP_MODEL_PROVIDER` | `auto` | `auto` uses OpenAI-compatible when a key is set, otherwise the mock. Also accepts `mock` or `openai` |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | unset, `https://api.openai.com/v1`, `gpt-4o-mini` | OpenAI-compatible adapter |
| `HOP_KILL_SWITCH` | `0` | `1` halts all provider and model calls |
| `HOP_OTEL_CONSOLE` | `0` | Also print spans to stdout |
| `HOP_USER`, `HOP_ROLE` | `local.analyst`, `analyst` | CLI identity defaults |
