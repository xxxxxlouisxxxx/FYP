# Runbook: DataForSEO SERP and search-volume collectors

- Capabilities: `dataforseo.serp.collect` and `dataforseo.demand.collect`. Manifests are in
  `hop/platform/capability_registry/manifests/`.
- Owner: data-platform-team
- Egress: `api.dataforseo.com` only, over HTTPS on port 443. Requests to any other host are denied and
  audited.
- Endpoints: `/v3/serp/google/organic/live/advanced` and
  `/v3/keywords_data/google_ads/search_volume/live`.

## Enable

1. Store the credentials as secrets `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD`. Never put them in
   YAML or in `.env` files that are committed.
2. Leave `HOP_SERP_PROVIDER=auto` so DataForSEO is used when credentials exist, or set it to
   `dataforseo` so that missing credentials fail the run instead.
3. Estimate first: `hop collection estimate-cost --market HK --tier A --provider dataforseo`. Unit costs
   are $0.002 per SERP task and $0.075 per search-volume task; the actual `cost` returned by DataForSEO
   is what gets recorded.
4. Run: `hop collection run --market HK --tier A --provider dataforseo`.

## Failure handling

| Symptom | Classification | Action |
|---|---|---|
| HTTP 429, 5xx, timeouts, or API status `5xxxx` | transient, retried with backoff | Resume the run later with `hop run resume <run_id>` |
| HTTP 401/403 or API status `40100` | permanent | Rotate the credentials, then start a new run |
| `PROVIDER_ERROR` observations for single queries | recorded per query | Those needs are UNKNOWN and are not treated as gaps. Rerun if needed |
| `ParseError` | permanent (payload contract change) | Pin the payload schema, update `parse_serp` and bump its parser version |
| Egress denied | policy | Check the manifest allowlist. Never widen it without a security review |

## Emergency stop

```bash
hop runtime kill-switch on --role platform_engineer --user <you> --reason "DataForSEO incident"
hop capability revoke dataforseo.serp.collect --reason "INC-123" --role platform_engineer --user <you>
```

Revocation takes effect at the next policy check. Running collectors stop before their next request.
