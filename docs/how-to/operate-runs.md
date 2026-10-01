# How to inspect a trace, test a rule and recover a run

## Inspect a trace

```bash
hop trace inspect --run latest                # span tree, collapsed below depth 3
hop trace inspect <trace_id> --max-depth 6 --attributes
curl -H 'X-HOP-Role: analyst' http://localhost:8000/traces/<trace_id>
```

API clients can send a W3C `traceparent` header. The API continues that trace, so the client's spans,
the API request span and the workflow spans all appear in one tree.

## Test a rule change

1. Edit `domain_packs/sports_footwear/rules/gap_rules.yaml`. Bump the rule's `version` and add a
   `tests:` case that covers the change.
2. Run `hop rule test`. Every rule must have at least one test, and all tests must pass.
3. Run `hop domain validate sports-footwear` and `make test`.
4. Run a sandbox collection and compare its cards with the previous run in the dashboard. Candidates
   and cards record `rule_id@rule_version`.

## Recover a failed or killed run

```bash
hop run list
hop run dead-letters                  # failure class, step and error for each dead letter
hop run resume <run_id>               # checkpointed steps are skipped
```

Failure classes map to run statuses as follows:

- `transient` and `timeout`: already retried with backoff. Resume once the provider has recovered.
- `kill_switch`: the run status is KILLED. Release the switch with
  `hop runtime kill-switch off --role platform_engineer`, then resume.
- `budget_exceeded`: the run status is REJECTED_BUDGET. Start a new run with
  `--budget <usd> --budget-approver "<name>"`.
- `policy_violation`: a capability was revoked or a tool was denied. Check
  `hop capability list`, the Platform Health → Policy tab, or `/policy/decisions`.

## Cancel a run

```bash
curl -X POST -H 'X-HOP-User: Sam Lee' -H 'X-HOP-Role: analyst' http://localhost:8000/runs/<run_id>/cancel
```
