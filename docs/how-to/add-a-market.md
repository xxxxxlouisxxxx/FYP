# How to add a market

Markets are configuration in the domain pack (`domain_packs/sports_footwear/markets/markets.yaml`).
Adding one needs no code change.

## 1. Dry-run the change

```bash
hop market add --code MY --name Malaysia \
  --locale en=en-MY=en \
  --location-code 2458 --currency MYR --timezone Asia/Kuala_Lumpur \
  --dry-run
```

- `--locale` is `language=locale=provider_language_code`. Repeat it for each language, for example
  `--locale zh-Hans=zh-MY=zh_CN`.
- `--location-code` is the DataForSEO location code.
- Tiers, budgets and devices are copied from `--template` (default `SG`).
- `--reference-volume` sets the monthly search volume that maps to a demand index of 1.0. Calibrate
  it for the market's size.

## 2. Apply and validate

```bash
hop market add ...same options without --dry-run...
hop domain validate sports-footwear
```

`market add` writes the YAML and then re-validates the whole pack. If validation fails, the file is
rolled back.

Queries whose `markets` list contains `"*"` apply to the new market automatically. To add
market-specific queries, add them to `taxonomy/queries.yaml` with `markets: [MY]`.

## 3. Provide data

You have two options:

- **Sandbox:** add recorded fixtures under `domain_packs/sports_footwear/sandbox/MY/`, using the same
  layout as `HK/` (`serp/`, `demand/`, `gerp/`). `write_market()` in
  `scripts/generate_sandbox_fixtures.py` writes them from a market profile (search engine, retailers,
  forums) and a per-need scenario table. `tests/e2e/test_market_onboarding.py` onboards MY exactly
  this way. It asserts that the run produces MY cards, that only `markets.yaml` and `sandbox/MY/`
  changed, and that no Python file under `hop/` changed.
- **Real provider:** set `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD`. See the
  [DataForSEO runbook](../runbooks/dataforseo-serp.md).

## 4. Run

```bash
hop collection estimate-cost --market MY --tier A
hop collection run --market MY --tier A
```

If there are no fixtures and no credentials, the run still succeeds, but every observation is
`NOT_COLLECTED`. Every gap rule then evaluates to `UNKNOWN`, and no cards are created. This is
intended: missing data is never read as a demand or supply gap (spec 8.4).

## 5. Commit

Commit the YAML change with the domain pack owner as reviewer. The content hash printed by
`hop domain validate` is recorded on every run and card, so each result can be traced back to the
exact configuration that produced it.
