# Runbook: incident response, kill switch and rollback

## Triage signals

The **Platform Health & Governance** dashboard page shows:

- failed and killed runs, with dead letters;
- policy denials, which can indicate a revoked capability, an egress attempt or a denied tool;
- cost per run against its budget;
- evaluation failures;
- the audit-chain status.

The same data is available from the CLI (`hop run list`, `hop run dead-letters`, `hop audit verify`)
and the API (`/policy/decisions`, `/costs`, `/audit`).

## 1. Stop the damage

| Situation | Command |
|---|---|
| Runaway cost, provider abuse, suspected compromise | `hop runtime kill-switch on --role platform_engineer --user <you> --reason "<INC-id>"`. This halts every provider request and model call at its next check. Runs in progress end as KILLED with a dead letter |
| One faulty capability (collector, extractor, explainer, exporter) | `hop capability revoke <capability_id> --reason "<INC-id>" --role platform_engineer --user <you>` |
| Whole deployment | Set `HOP_KILL_SWITCH=1` in the environment. This cannot be released from the CLI |

Every one of these actions is audited with your name and reason.

## 2. Assess

- `hop trace inspect --run <run_id> --attributes` shows which capability, model, prompt version and
  step were involved.
- `hop audit list --limit 100` lists recent events. Run `hop audit verify` to confirm that no event
  was altered.
- For injection or content incidents, the raw payloads are in the object store. Evidence items
  record the `PROMPT_INJECTION_SUSPECTED` flag and quarantine state.

## 3. Roll back

- **Configuration** (rules, scoring, prompts, markets): revert the domain-pack commit, then run
  `hop domain validate sports-footwear` and `hop rule test`. Cards record the rule, score and pack
  versions, so you can find the cards created under a bad version with
  `hop opportunity export --format csv`.
- **Model or prompt:** revert the prompt version in `prompts/prompts.yaml`, or set
  `HOP_MODEL_PROVIDER=mock`, and run `hop evaluation run`. The quality ratchet blocks a regression
  against the recorded champion.
- **Code:** redeploy the previous image tag. The database schema is additive, so older builds can read
  newer rows.
- **Cards created during the incident:** reject them with a rationale, or reopen approved ones
  (`hop opportunity review <id> --action REOPEN --rationale "<INC-id>"`). History is never deleted.

## 4. Recover

```bash
hop capability reinstate <capability_id> --role platform_engineer --user <you>
hop runtime kill-switch off --role platform_engineer --user <you> --reason "<INC-id> resolved"
hop run resume <run_id>
```

Record the incident, its root cause and the evaluation cases added to prevent it from recurring.
