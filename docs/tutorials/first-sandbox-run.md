# Tutorial: your first sandbox run and your first Opportunity Card

This tutorial takes you from a clean checkout to an approved Opportunity Card, using only recorded
sandbox data. You will not need any credentials. It meets the onboarding benchmark in spec 16.2:
validate the domain pack, run a sandbox sample, inspect its trace and open a Draft Opportunity Card.

You need Python 3.11 or newer and `make`.

## 1. Install

```bash
make install            # creates .venv and installs hop with the dashboard and dev extras
source .venv/bin/activate
```

All state goes to `var/` (a SQLite database, `var/hop.db`, and an object store, `var/objects/`).
To keep experiments separate, set `HOP_DATA_DIR=/some/dir`.

## 2. Validate the domain pack

```bash
hop domain validate sports-footwear
hop rule test
```

`domain validate` checks every YAML file against its schema, and checks cross-references between
queries, needs, attributes and brands. It then loads the product extensions (gap rules, admission
policy, scoring rubric and quality ratchet) and runs the tests embedded in each gap rule. It ends with
`Domain pack sports-footwear is valid.`

## 3. Estimate, then run

```bash
hop collection estimate-cost --market HK --tier A
hop collection run --market HK --tier A
```

The estimate lists the planned SERP tasks, search-volume tasks and model calls, and compares their
cost with the tier budget ($5.00 for HK tier A). No spend happens until you run.

The run executes the 15 workflow steps from spec 7 and prints a table of steps, then the Draft
Opportunity Cards and the candidates that did not pass the admission gates. With the sandbox you
should see:

- `collect_serp`: `PROVIDER_ERROR=1`. The vegan query's SERP task fails on purpose.
- `normalise`: `NOT_COLLECTED=1`. The budget-shoe search volume is `null` at the provider. It stays
  missing and is never turned into zero.
- `collect_gerp`: `injection_flagged_answers=1`. One recorded answer contains a prompt injection. It
  is flagged and cannot be used as supporting evidence.
- `gap_detection` finds 12 candidates, and `admission_gates` admits 8 of them. The other 4 fail
  either `independent_signal_families` (only one signal family) or `entity_ambiguity` (the bare word
  "On" could be the brand On Running or an ordinary word).
- `create_cards`: `cards_created=8`, split into HIGH, MEDIUM and LOW priority.

Running the same command again the same day returns the same run, because runs are idempotent. Add
`--force-new` to start a fresh run.

## 4. Inspect the trace

```bash
hop run inspect latest
hop trace inspect --run latest
```

The trace tree starts with `Opportunity Discovery Run`. Its child spans are `Configuration validation`,
`Cost estimation`, the collection steps, `Model call` spans (with `Prompt rendering`), `Normalisation`,
`Entity resolution`, `Data-quality checks`, `Gap detection`, `Counter-evidence`, `Admission gates`,
`Scoring`, `Opportunity Card creation` and `Evaluation`. Add `--attributes` to see capability ids,
model ids, prompt versions, token counts, costs and retry counts.

## 5. Open a Draft Opportunity Card

```bash
hop opportunity list
hop opportunity show <card_id>
```

Each card contains:

- the score broken down into components and penalties;
- evidence-linked OBSERVED, INFERRED, UNKNOWN and LIMITATION statements;
- the counter-evidence that was considered;
- the sample sizes behind every rate (n and a 95% Wilson interval);
- the required approver role.

## 6. Review it

A HIGH-priority card needs the `review_board` role and a named reviewer:

```bash
hop opportunity approve <card_id> --owner "Sourcing Desk HK"                       # analyst: denied (exit 3)
hop opportunity approve <card_id> --owner "Sourcing Desk HK" \
    --reviewer "Ada Chan" --role review_board                                        # approved
hop opportunity review <other_card_id> --action WATCHLIST --rationale "wait for Q4 volume" \
    --reviewer "Sam Lee" --role analyst
hop audit verify
```

Draft cards are moved to In Review automatically when a decision is recorded. Every transition is
stored as a ReviewDecision and as a hash-chained audit event.

## 7. Use the dashboard

```bash
make dashboard      # http://localhost:8501
```

Pick your role and name in the sidebar and choose the run. The seven pages follow spec 14. In
**Opportunity Evidence Room**, select a card, enter an owner and press **Approve**.

## 8. Next steps

- [Add a market](../how-to/add-a-market.md)
- [Inspect a trace, test a rule, recover a run](../how-to/operate-runs.md)
- [CLI reference](../reference/cli.md) and [API and permissions](../reference/api-and-permissions.md)
