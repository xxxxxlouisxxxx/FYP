# ADR 0001: Three-layer package layout under a single `hop` package

- Status: Accepted
- Date: 2026-09-30
- Spec: implementation plan v4.0, sections 4.1, 4.2, 16.1 and 24 (action 2)

## Context

The v4.0 plan separates a reusable **platform core**, an **Opportunity Intelligence product** and a
**sports-footwear domain pack** (spec 4.1). Section 16.1 draws the repository as top-level
`platform/`, `products/` and `domain_packs/` directories.

A top-level Python package literally named `platform` would shadow the standard-library module
`platform`, which is imported by pip, SQLAlchemy, httpx, Streamlit, uvicorn and pytest. Anything that
runs with the repository root on `sys.path` (pytest, `streamlit run`, `python -m`) would break in
confusing ways.

## Decision

1. Python code lives in one distribution package, `hop`, with the spec's layers as sub-packages:

   | Spec 16.1 path | Package |
   |---|---|
   | `platform/` | `hop.platform` (`api`, `workflow_runtime`, `model_gateway`, `evidence_service`, `capability_registry`, `policy_engine`, `evaluation`, `observability`, `common_contracts`, plus `storage`, `audit`, `integrations`, `entity_resolution`, `domain_registry`, `analytics`) |
   | `products/opportunity_intelligence/` | `hop.products.opportunity_intelligence` (`gap_detection`, `counter_evidence`, `scoring`, `opportunity_lifecycle`, `dashboard`) |
   | `domain_packs/sports_footwear/` | `domain_packs/sports_footwear/` (YAML plus sandbox fixtures, no Python) |
   | `infrastructure/` | `infrastructure/` (containers, compose, backup) |

2. **Dependency rule.** `hop.platform` never imports `hop.products`, `hop.bootstrap` or anything
   under `domain_packs/`, and contains no footwear vocabulary. Products depend on the platform. Domain
   packs are data validated by the platform's domain registry and by product-declared extension schemas
   (`pack.yaml` `extensions:`).
3. **Composition root.** `hop/bootstrap.py` is the only module that wires all three layers. The
   entry points (`hop/cli`, `hop/api.py`, the Streamlit app) call `build_app()`.
4. The rule is enforced by `tests/contract/test_contracts.py::test_platform_core_is_domain_agnostic`,
   which scans every `hop/platform` module's imports and text. A second test guards against a
   top-level `platform` package being reintroduced.

## Consequences

- Every layer boundary from the spec is visible in import paths (`hop.platform.model_gateway`), and
  a reviewer can find the layer of any module from its name.
- A second domain (for example apparel) is a new `domain_packs/<id>/` directory plus, if needed, a new
  product package. No platform changes are required. `hop market add` already onboards markets by
  configuration.
- Packaging is a single wheel. If the platform is later published separately, `hop.platform` can be
  split out without renaming imports, because it already has no upward dependencies.
