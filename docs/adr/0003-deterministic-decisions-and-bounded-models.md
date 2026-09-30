# ADR 0003: Deterministic scoring and gating; models only extract and explain

- Status: Accepted
- Date: 2026-09-30
- Spec: 6.3, 7.1, 8.4, 9.5, 12.2

## Decision

- **Deterministic code** computes every number a decision depends on:
  - demand index, supply shares, recommendation coverage, HHI and Wilson intervals;
  - gap-rule evaluation;
  - the ten admission gates;
  - the six-component score, its penalties and the priority band.
  All of these are versioned YAML in the domain pack (`rules/`, `scoring/`) and are unit-tested
  (`hop rule test`).
- **Models** (through `hop.platform.model_gateway`) are used for only three bounded tasks:
  - observing generative answers (GERP);
  - labelling brand mentions (primary recommendation, supporting recommendation, mention, exclusion);
  - drafting a card summary.
- **Gateway checks on every call:**
  - capability manifest status and the tool grant `model.invoke`;
  - the model allowlist;
  - input size, the budget reservation and the kill switch;
  - retries and timeout;
  - persistence of the prompt and response hash.
  Untrusted variables are wrapped in `<untrusted_content>` and scanned for injection patterns.
- **Model output validation:** outputs are validated against Pydantic schemas. Extraction spans must
  match the source text exactly. The card summary may only cite the card's own evidence ids, and any
  number it contains must appear in the deterministic facts. Otherwise the template explanation is
  used, and the validation notes are recorded on the card.
- **Missing data (spec 8.4):**
  - `MeasuredValue` and `Proportion` carry one of eight states. A missing value never carries a number.
  - Rule conditions over missing inputs are UNKNOWN, so a rule cannot fire on them.
  - Score components with missing inputs contribute nothing and are labelled `MISSING`.
  - Risk penalties apply conservatively when their input is missing.
- **Mock model default:** without `OPENAI_API_KEY` the gateway uses `mock-gerp-1`. This is a
  deterministic adapter that replays recorded sandbox answers and runs a rule-based labeller. It lets
  the full workflow, the golden-set evaluation and the tests run offline. Cards record the model id,
  so simulated output is always identifiable.

## Consequences

- Scores are reproducible and explainable component by component. Sensitivity (±0.05 on each weight)
  is shown on each card.
- Model quality problems show up as abstentions or template fallbacks. They are never turned into
  silent numeric errors.
- The golden sets are small development partitions built together with the mock labeller, so their
  1.0 scores prove that the harness and ratchet work, not that a model is accurate. Binding thresholds
  need a held-out partition labelled by analysts (Phase 3).
