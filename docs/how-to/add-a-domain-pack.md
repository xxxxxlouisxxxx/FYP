# How to add a domain pack

A domain pack is a directory of YAML (plus optional sandbox fixtures) under `domain_packs/`. The
platform runtime and the Opportunity Intelligence product read everything domain-specific from it,
so a new domain needs no code change. `domain_packs/outdoor_apparel/` is a worked proof of concept
(spec 2.2).

## 1. Create the pack

Copy the layout of an existing pack and edit the content:

| File | What to change |
| --- | --- |
| `pack.yaml` | `pack_id` (kebab-case; the directory may use underscores), name, version, owner |
| `markets/markets.yaml`, `markets/source_types.yaml` | Markets and tiers; which domains count as manufacturer, retailer or marketplace (supply sources) |
| `brands/brands.yaml` | Brand registry. Mark an alias `ambiguous: true` and give it `context_patterns` if it can mean something else (`Columbia` in the apparel pack) |
| `taxonomy/needs.yaml`, `taxonomy/queries.yaml`, `attributes/attributes.yaml` | Consumer needs, their `match_terms` (what counts as on-need supply in the SERP), and the queries to collect |
| `prompts/prompts.yaml` | Governed prompts, including the recommendation, supporting and exclusion cues |
| `rules/`, `scoring/` | Gap rules (with embedded tests), admission gates, and the score rubric. `score_version` must look like `score-vX.Y.Z` |
| `evaluation_sets/` | Golden sets for label extraction and entity resolution, plus the quality ratchet |

## 2. Validate

```bash
hop domain validate outdoor-apparel
HOP_DOMAIN_PACK=outdoor-apparel hop rule test
HOP_DOMAIN_PACK=outdoor-apparel hop evaluation run
```

Validation checks every file against its schema, runs the embedded rule tests, and prints the content
hash that each run and card records.

## 3. Provide data and run

For the sandbox, write recorded provider payloads under `sandbox/<MARKET>/{serp,demand,gerp}/`.
`scripts/generate_outdoor_apparel_fixtures.py` shows how to build them from a small scenario table.
It reuses the DataForSEO payload shapes, so the same parsers read sandbox and live data.

```bash
HOP_DOMAIN_PACK=outdoor-apparel hop collection run --market HK --tier A
HOP_DOMAIN_PACK=outdoor-apparel make dashboard
```

Packs can share one database. Every run and card records its `domain_pack`, rule version and score
version.

## What the tests guarantee

`tests/e2e/test_second_domain_pack.py` checks four things:

- The apparel pack contains only YAML and JSON.
- No Python file under `hop/` mentions the pack or its content.
- Its rules and golden sets pass.
- It runs through the same workflow (same name, version and steps) as sports-footwear, producing
  cards with verifiable lineage.
