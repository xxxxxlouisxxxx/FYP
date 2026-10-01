# hop CLI reference

HKTDC Hidden Opportunity Discovery Platform (walking skeleton).

**Usage**:

```console
$ hop [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--install-completion`: Install completion for the current shell.
* `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
* `--help`: Show this message and exit.

**Commands**:

* `domain`: Domain packs.
* `market`: Markets in a domain pack.
* `collection`: Collection runs (the spec 7 discovery...
* `run`: Workflow runs.
* `trace`: OpenTelemetry traces.
* `evaluation`: Evaluation harness.
* `rule`: Gap rules.
* `opportunity`: Opportunity Cards.
* `capability`: Capability registry.
* `runtime`: Runtime controls.
* `schema`: Contract JSON Schemas.
* `audit`: Audit log.

## `hop domain`

Domain packs.

**Usage**:

```console
$ hop domain [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `validate`: Validate a domain pack (schemas,...

### `hop domain validate`

Validate a domain pack (schemas, cross-references, product rules, gap-rule tests).

**Usage**:

```console
$ hop domain validate [OPTIONS] [pack_id]
```

**Arguments**:

* `pack_id`: Domain pack id  [default: sports-footwear]

**Options**:

* `--help`: Show this message and exit.

## `hop market`

Markets in a domain pack.

**Usage**:

```console
$ hop market [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `add`: Add a market to a domain pack (validated;...

### `hop market add`

Add a market to a domain pack (validated; rolled back if the pack becomes invalid).

**Usage**:

```console
$ hop market add [OPTIONS]
```

**Options**:

* `--code <str>`: ISO 3166 alpha-2 market code, e.g. MY  [required]
* `--name <str>`: Display name  [required]
* `--locale <str>`: language=locale=provider_language_code, e.g. en=en-MY=en  [required]
* `--location-code <int>`: DataForSEO location code  [required]
* `--currency <str>`: [required]
* `--timezone <str>`: [required]
* `--reference-volume <int>`: Monthly volume mapped to demand index 1.0  [default: 5000]
* `--freshness-days <int>`: [default: 30]
* `--template <str>`: Copy tiers and devices from this market  [default: SG]
* `--pack <str>`: [default: sports-footwear]
* `--dry-run / --no-dry-run`: Validate without writing  [default: no-dry-run]
* `--help`: Show this message and exit.

## `hop collection`

Collection runs (the spec 7 discovery workflow).

**Usage**:

```console
$ hop collection [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `estimate-cost`: Estimate the cost of a collection run...
* `run`: Run the discovery workflow end to end and...

### `hop collection estimate-cost`

Estimate the cost of a collection run before any spend.

**Usage**:

```console
$ hop collection estimate-cost [OPTIONS]
```

**Options**:

* `--market <str>`: [default: HK]
* `--tier <str>`: [default: A]
* `--language <str>`
* `--repeats <int>`: GERP repeats per query (default from tier)
* `--provider <str>`: auto | sandbox | dataforseo  [default: auto]
* `--help`: Show this message and exit.

### `hop collection run`

Run the discovery workflow end to end and create Draft Opportunity Cards.

**Usage**:

```console
$ hop collection run [OPTIONS]
```

**Options**:

* `--market <str>`: [default: HK]
* `--tier <str>`: [default: A]
* `--language <str>`
* `--repeats <int>`: GERP repeats per query (default from tier)
* `--budget <float>`: Run budget in USD (default: tier limit)
* `--budget-approver <str>`: Named approver for budgets above the tier limit
* `--provider <str>`: auto | sandbox | dataforseo  [default: auto]
* `--question <str>`: Decision question this run supports
* `--force-new / --no-force-new`: Start a new run even if an identical request ran today  [default: no-force-new]
* `--user <str>`: [default: local.analyst]
* `--role <str>`: [default: analyst]
* `--json`: Print the run as JSON
* `--help`: Show this message and exit.

## `hop run`

Workflow runs.

**Usage**:

```console
$ hop run [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: List recent runs.
* `inspect`: Show a run: steps, costs, candidates and...
* `resume`: Resume a failed/killed run from its last...
* `cancel`: Cancel a run (checked between activities).
* `dead-letters`: Show failed steps in the dead-letter table.

### `hop run list`

List recent runs.

**Usage**:

```console
$ hop run list [OPTIONS]
```

**Options**:

* `--limit <int>`: [default: 20]
* `--help`: Show this message and exit.

### `hop run inspect`

Show a run: steps, costs, candidates and cards.

**Usage**:

```console
$ hop run inspect [OPTIONS] [run_id]
```

**Arguments**:

* `run_id`: [default: latest]

**Options**:

* `--json`
* `--help`: Show this message and exit.

### `hop run resume`

Resume a failed/killed run from its last checkpoint.

**Usage**:

```console
$ hop run resume [OPTIONS] {run_id}
```

**Arguments**:

* `run_id`: [required]

**Options**:

* `--user <str>`: [default: local.analyst]
* `--role <str>`: [default: analyst]
* `--help`: Show this message and exit.

### `hop run cancel`

Cancel a run (checked between activities).

**Usage**:

```console
$ hop run cancel [OPTIONS] {run_id}
```

**Arguments**:

* `run_id`: [required]

**Options**:

* `--user <str>`: [default: local.analyst]
* `--help`: Show this message and exit.

### `hop run dead-letters`

Show failed steps in the dead-letter table.

**Usage**:

```console
$ hop run dead-letters [OPTIONS]
```

**Options**:

* `--limit <int>`: [default: 20]
* `--help`: Show this message and exit.

## `hop trace`

OpenTelemetry traces.

**Usage**:

```console
$ hop trace [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `inspect`: Print the span tree for a trace...

### `hop trace inspect`

Print the span tree for a trace (Opportunity Discovery Run and children).

**Usage**:

```console
$ hop trace inspect [OPTIONS] [trace_id]
```

**Arguments**:

* `trace_id`

**Options**:

* `--run <str>`: Run id (or &#x27;latest&#x27;) instead of a trace id
* `--max-depth <int>`: Collapse spans deeper than this  [default: 3]
* `--attributes`
* `--help`: Show this message and exit.

## `hop evaluation`

Evaluation harness.

**Usage**:

```console
$ hop evaluation [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `run`: Run golden-set evaluations and compare...

### `hop evaluation run`

Run golden-set evaluations and compare against the quality ratchet and champion.

**Usage**:

```console
$ hop evaluation run [OPTIONS]
```

**Options**:

* `--suite <str>`: Suite id(s); default all
* `--user <str>`: [default: local.analyst]
* `--role <str>`: [default: analyst]
* `--help`: Show this message and exit.

## `hop rule`

Gap rules.

**Usage**:

```console
$ hop rule [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `test`: Run the unit tests embedded in the...

### `hop rule test`

Run the unit tests embedded in the gap-rule definitions.

**Usage**:

```console
$ hop rule test [OPTIONS]
```

**Options**:

* `--rule-set <str>`
* `--help`: Show this message and exit.

## `hop opportunity`

Opportunity Cards.

**Usage**:

```console
$ hop opportunity [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: List Opportunity Cards ordered by score.
* `show`: Show one Opportunity Card with its score...
* `review`: Move a card through Draft -&gt; In Review -&gt;...
* `approve`: Approve a card (shortcut for review...
* `export`: Export Opportunity Cards with lineage and...

### `hop opportunity list`

List Opportunity Cards ordered by score.

**Usage**:

```console
$ hop opportunity list [OPTIONS]
```

**Options**:

* `--status <str>`
* `--market <str>`
* `--run <str>`
* `--help`: Show this message and exit.

### `hop opportunity show`

Show one Opportunity Card with its score breakdown, statements and review history.

**Usage**:

```console
$ hop opportunity show [OPTIONS] {card_id}
```

**Arguments**:

* `card_id`: [required]

**Options**:

* `--json`
* `--help`: Show this message and exit.

### `hop opportunity review`

Move a card through Draft -&gt; In Review -&gt; Approved / Watchlist / Rejected.

**Usage**:

```console
$ hop opportunity review [OPTIONS] {card_id}
```

**Arguments**:

* `card_id`: [required]

**Options**:

* `--action <submit_for_review|approve|watchlist|reject|reopen>`: [required]
* `--reviewer <str>`: [default: local.analyst]
* `--role <str>`: [default: analyst]
* `--rationale <str>`
* `--owner <str>`
* `--proposed-action <str>`
* `--help`: Show this message and exit.

### `hop opportunity approve`

Approve a card (shortcut for review --action APPROVE).

**Usage**:

```console
$ hop opportunity approve [OPTIONS] {card_id}
```

**Arguments**:

* `card_id`: [required]

**Options**:

* `--reviewer <str>`: [default: local.analyst]
* `--role <str>`: [default: analyst]
* `--owner <str>`: Accountable owner  [required]
* `--rationale <str>`
* `--proposed-action <str>`
* `--help`: Show this message and exit.

### `hop opportunity export`

Export Opportunity Cards with lineage and versions (governed by opportunity.exporter).

**Usage**:

```console
$ hop opportunity export [OPTIONS]
```

**Options**:

* `--format <str>`: json | csv  [default: json]
* `--out <path>`: Also write to this local file
* `--status <str>`
* `--market <str>`
* `--user <str>`: [default: local.analyst]
* `--role <str>`: [default: analyst]
* `--help`: Show this message and exit.

## `hop capability`

Capability registry.

**Usage**:

```console
$ hop capability [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: List registered capabilities with status,...
* `revoke`: Revoke a capability (takes effect...
* `reinstate`: Reinstate a revoked capability.

### `hop capability list`

List registered capabilities with status, tools and egress allowlist.

**Usage**:

```console
$ hop capability list [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

### `hop capability revoke`

Revoke a capability (takes effect immediately for every workflow).

**Usage**:

```console
$ hop capability revoke [OPTIONS] {capability_id}
```

**Arguments**:

* `capability_id`: [required]

**Options**:

* `--reason <str>`: [required]
* `--user <str>`: [default: local.analyst]
* `--role <str>`: [default: analyst]
* `--help`: Show this message and exit.

### `hop capability reinstate`

Reinstate a revoked capability.

**Usage**:

```console
$ hop capability reinstate [OPTIONS] {capability_id}
```

**Arguments**:

* `capability_id`: [required]

**Options**:

* `--user <str>`: [default: local.analyst]
* `--role <str>`: [default: analyst]
* `--help`: Show this message and exit.

## `hop runtime`

Runtime controls.

**Usage**:

```console
$ hop runtime [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `kill-switch`: Engage or release the global kill switch...

### `hop runtime kill-switch`

Engage or release the global kill switch (stops provider and model calls at the next check).

**Usage**:

```console
$ hop runtime kill-switch [OPTIONS] {state}
```

**Arguments**:

* `state`: on | off | status  [required]

**Options**:

* `--reason <str>`: [default: operator action]
* `--user <str>`: [default: local.analyst]
* `--role <str>`: [default: analyst]
* `--help`: Show this message and exit.

## `hop schema`

Contract JSON Schemas.

**Usage**:

```console
$ hop schema [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `export`: Export JSON Schemas for all published...

### `hop schema export`

Export JSON Schemas for all published contracts.

**Usage**:

```console
$ hop schema export [OPTIONS]
```

**Options**:

* `--out <path>`: [default: docs/reference/schemas]
* `--help`: Show this message and exit.

## `hop audit`

Audit log.

**Usage**:

```console
$ hop audit [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `verify`: Verify the audit log hash chain.
* `list`: Show recent audit events.

### `hop audit verify`

Verify the audit log hash chain.

**Usage**:

```console
$ hop audit verify [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

### `hop audit list`

Show recent audit events.

**Usage**:

```console
$ hop audit list [OPTIONS]
```

**Options**:

* `--resource <str>`
* `--limit <int>`: [default: 30]
* `--help`: Show this message and exit.
