# HKTDC Sports Footwear Hidden Opportunity Discovery Platform
## Enterprise AI Platform Implementation Plan v4.0

**Document status:** Implementation-ready baseline  
**Scope:** Level 2 Hidden Opportunity Discovery  
**Primary domain:** Sports footwear, initially running shoes  
**Primary users:** HKTDC market-intelligence analysts, research managers, domain reviewers, platform engineers and authorised decision-makers  
**Delivery interface:** Streamlit decision-intelligence dashboard, supported by APIs, CLI and governed data products  
**Version:** 4.0  
**Date:** 29 September 2026

---

## 1. Executive summary

This document upgrades the Level 2 Hidden Opportunity Discovery solution from a production-oriented multi-agent application into an **enterprise AI platform with a reusable domain product**.

The platform answers four connected questions:

1. **What are consumers and trade buyers asking for?**
2. **What do search engines display?**
3. **What do generative engines recommend, omit or contradict?**
4. **Which unmet needs provide credible, evidence-backed opportunities for HKTDC and its stakeholders?**

The design separates three concerns:

- **Enterprise AI Platform Layer:** reusable runtime, evidence, evaluation, observability, security, registry, workflow and self-service capabilities.
- **Opportunity Intelligence Product Layer:** gap detection, counter-evidence, scoring, prioritisation and opportunity lifecycle management.
- **Sports Footwear Domain Pack:** footwear taxonomies, brand aliases, consumer needs, product attributes, markets, rules, benchmarks and prompts.

This separation ensures that sports-footwear logic does not contaminate the reusable platform core. Future HKTDC sectors can reuse the same platform by installing a different domain pack rather than rebuilding the system.

The platform is a **decision-support system**, not an autonomous decision-maker. High-impact opportunity recommendations require traceable evidence, automated quality gates and accountable human approval.

---

## 2. Business outcomes

### 2.1 Target outcomes

The platform shall:

- detect unmet or underserved sports-footwear needs across selected markets;
- compare consumer demand, search visibility and generative-engine recommendations;
- identify brand, product-attribute, market and information gaps;
- distinguish genuine gaps from missing, stale or low-quality data;
- attach supporting and counter-evidence to every opportunity;
- quantify confidence, sample size, freshness and stability;
- support analyst review, challenge, approval, rejection and re-evaluation;
- reduce time from raw signal to review-ready Opportunity Card;
- provide a reusable foundation for additional HKTDC industries.

### 2.2 Business value measures

Initial 90-day production targets:

- at least 90% of published Opportunity Cards contain valid supporting evidence and counter-evidence;
- 100% of high-priority opportunities receive human approval;
- zero published opportunities without evidence lineage, score version and review status;
- median collection-to-draft time below 24 hours for scheduled runs;
- analyst acceptance or watchlist rate above 60% after calibration;
- false-opportunity rate below 10% on a reviewed validation sample;
- at least 95% successful scheduled pipeline runs, excluding provider outages;
- replay of any published opportunity from retained evidence and version metadata;
- onboarding of one additional market without core-code changes;
- creation of a second domain-pack proof of concept without changing platform runtime services.

Targets must be recalibrated after the first labelled production sample. They are quality gates, not claims of guaranteed model performance.

---

## 3. Scope and boundaries

### 3.1 In scope

- consumer-query and need discovery;
- DataForSEO or equivalent provider collection adapters;
- SERP feature, ranking, source and brand visibility analysis;
- governed LLM-based generative-engine observation;
- brand, product, attribute, need and source entity resolution;
- supporting-evidence and counter-evidence extraction;
- hidden-opportunity detection and prioritisation;
- statistical confidence, stability and freshness assessment;
- analyst review and decision workflow;
- Streamlit dashboard;
- APIs and CLI for governed self-service;
- evaluation, observability, security, audit and cost controls;
- reusable platform interfaces and sports-footwear domain pack.

### 3.2 Out of scope

- automatic procurement, investment or supplier-selection decisions;
- automatic publishing of market claims without human approval;
- direct modification of third-party search or generative-engine systems;
- autonomous outreach to companies or consumers;
- transactional execution;
- full enterprise marketplace for all future HKTDC agents in the first release;
- causal claims that market demand will convert into revenue without experiments.

### 3.3 Decision-right boundary

The system may **observe, classify, compare, score, explain and recommend**. It must not independently approve high-priority opportunities, make contractual commitments, publish external claims or trigger irreversible business actions.

---

## 4. Enterprise architecture

### 4.1 Three-layer architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│  Experience and Decision Layer                                 │
│  Streamlit | Review Queue | Opportunity Portfolio | Exports    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  Opportunity Intelligence Product Layer                        │
│  Need Discovery | SERP–GERP Comparison | Gap Detection         │
│  Counter-Evidence | Scoring | Opportunity Lifecycle            │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  Enterprise AI Platform Layer                                  │
│  Workflow Runtime | Model Gateway | Evidence Service           │
│  Evaluation | Observability | Registry | Policy | Identity     │
│  Cost Control | Data Quality | Human Review | Self-Service     │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  Governed Data and Integration Layer                            │
│  PostgreSQL | Object Storage | Redis | Providers | Exports     │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  Sports Footwear Domain Pack                                   │
│  Taxonomy | Brand Registry | Attribute Ontology | Rules        │
│  Prompts | Evaluation Sets | Market Configuration              │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Mandatory architectural principles

1. **Evidence before conclusion:** no opportunity may be published without traceable evidence.
2. **Deterministic code before LLM:** calculations, gates, access control, hashes and policy enforcement remain deterministic.
3. **Configuration before custom code:** markets, brands, rules, rubrics and domain concepts use validated configuration.
4. **Human accountability:** material business recommendations require named human owners.
5. **Least privilege:** every agent receives only the tools, data and network access required for the task.
6. **Replayability:** a published output can be reconstructed from evidence and versioned artefacts.
7. **Replaceability:** model, data-provider and storage adapters use explicit contracts.
8. **Observable by default:** every run produces correlated traces, metrics, logs, evaluation events and cost records.
9. **Safe failure:** low confidence, unavailable data or validation failure produces abstention, not fabricated completion.
10. **Platform product thinking:** reusable services have owners, service levels, documentation and adoption measures.

---

## 5. Core platform capabilities

### 5.1 Workflow runtime

The runtime orchestrates deterministic services and bounded agents through explicit state transitions.

Required controls:

- idempotent job keys;
- retry policies with exponential backoff and jitter;
- timeout per activity and total run;
- maximum agent steps;
- dead-letter queue;
- cancellation and emergency kill switch;
- resumable checkpoints;
- concurrency and provider-rate limits;
- per-run budget;
- failure classification;
- manual replay from an approved checkpoint.

Recommended first implementation:

- FastAPI for control APIs;
- a durable worker framework such as Celery with Redis for the initial deployment;
- migration path to Temporal when long-running orchestration, advanced replay and multi-workflow dependencies justify the additional operational complexity.

### 5.2 Model gateway

All model calls must pass through one governed gateway rather than allowing agents to call models directly.

The gateway provides:

- approved provider and model allowlist;
- model routing and fallback policy;
- prompt-template resolution;
- schema-constrained outputs;
- input/output size limits;
- token and monetary budget checks;
- timeout and retry policy;
- redaction and data-classification checks;
- request/response audit metadata;
- caching only where privacy and semantic validity permit;
- structured abstention on failure;
- evaluation hooks;
- model and prompt version capture.

### 5.3 Evidence service

The Evidence Service is the authoritative link between raw observations and business conclusions.

Every evidence item includes:

- `evidence_id`;
- evidence type;
- source provider and endpoint;
- market, locale, language and device;
- query or prompt identifier;
- observation timestamp;
- raw payload URI;
- SHA-256 content hash;
- parser and schema version;
- model and prompt version where applicable;
- extracted claim and source span;
- entity references;
- data-quality status;
- access classification;
- retention class;
- cost attribution;
- trace ID.

Evidence is immutable. Corrections create a new version and preserve prior history.

### 5.4 Capability registry

Collectors, agents, rules, evaluators and exporters are registered capabilities rather than informal modules.

Each capability record includes:

```yaml
capability_id: dataforseo.serp.collect
version: 1.0.0
owner: data-platform-team
status: approved
input_schema: serp_collection_request_v1
output_schema: serp_observation_v2
permissions:
  - provider.dataforseo.task_post
  - object_store.raw_write
network_policy:
  outbound_allowlist:
    - api.dataforseo.com
slo:
  availability: 0.99
  p95_completion_minutes: 15
cost_model:
  unit: provider_task
documentation:
  runbook: docs/runbooks/dataforseo-serp.md
```

Registry promotion states:

```text
Draft → Tested → Approved → Deprecated → Retired
```

### 5.5 Configuration and domain-pack registry

All configuration is validated with Pydantic and published JSON Schema.

Versioned artefacts include:

- markets and locales;
- devices;
- brands and aliases;
- products and categories;
- need taxonomy;
- product-attribute ontology;
- data providers;
- collection templates;
- prompts;
- extraction schemas;
- gap rules;
- admission gates;
- scoring rubrics;
- evaluation suites;
- dashboard definitions.

No unvalidated YAML or free-form configuration may be promoted to production.

### 5.6 Self-service interface

Authorised analysts and engineers receive CLI and API workflows with safe defaults.

Illustrative CLI:

```bash
hop domain validate sports-footwear
hop market add HK --language en --device mobile
hop collection estimate-cost --market HK --tier A
hop collection run --market HK --tier A
hop run inspect RUN_ID
hop trace inspect TRACE_ID
hop evaluation run gerp-recommendation-v1
hop rule test gap-rule-v3
hop opportunity export --status approved
```

Self-service operations must enforce RBAC, policy, budget and audit requirements. Self-service does not mean bypassing governance.

---

## 6. Agent and deterministic-service design

### 6.1 Agent portfolio

| Component | Type | Responsibility | Must not do |
|---|---|---|---|
| Query Discovery Agent | LLM-assisted | classify and expand consumer/trade needs | invent search volume |
| SERP Collector | deterministic service | retrieve and persist provider observations | interpret business opportunity |
| GERP Observation Agent | bounded agent | run governed prompts and extract recommendations | calculate final KPI values |
| Entity Resolution Service | hybrid | resolve brands, products, sources and attributes | silently merge ambiguous entities |
| Evidence Extraction Agent | bounded agent | extract claims and evidence spans | publish unsupported claims |
| Counter-Evidence Agent | bounded agent | search within acquired evidence for contradictory signals | suppress contradictions |
| Gap Detection Engine | deterministic rules | identify qualified gaps | change rules at runtime |
| Scoring Engine | deterministic service | calculate confidence, value and feasibility scores | use hidden LLM arithmetic |
| Explanation Agent | bounded agent | produce evidence-linked summaries | introduce new facts |
| Evaluation Agent | hybrid | run metric suites and regression comparison | promote a version alone |
| Governance Agent | policy assistant | flag policy, lineage and approval exceptions | grant access or override policy |
| Observability Agent | operational assistant | summarise run health and anomalies | alter telemetry records |
| Experimentation Agent | hybrid | configure shadow and controlled experiments | declare causal impact without design |

### 6.2 Agent execution contract

Each agent invocation must declare:

- agent and capability version;
- purpose;
- input and output schema;
- allowed tools;
- permitted evidence classes;
- outbound network policy;
- model policy;
- maximum steps;
- timeout;
- token and expenditure budget;
- abstention conditions;
- evaluation suite;
- owner;
- trace context.

Example:

```yaml
agent_id: opportunity.counter_evidence
version: 2.0.0
purpose: identify evidence that weakens a proposed opportunity
allowed_tools:
  - evidence.search
  - taxonomy.lookup
network_access: none
max_steps: 8
max_duration_seconds: 120
max_cost_usd: 0.50
output_schema: counter_evidence_result_v2
abstain_when:
  - insufficient_evidence
  - conflicting_entity_resolution
human_review: required_for_high_priority
```

### 6.3 Deterministic responsibilities

The following must not rely on unconstrained model judgement:

- authentication and authorisation;
- secrets handling;
- hashing and deduplication;
- URL validation and normalisation;
- rate and budget limits;
- retries and timeouts;
- schema validation;
- numerical KPI calculation;
- Wilson confidence intervals;
- concentration, volatility and trend calculations;
- rule evaluation;
- scoring arithmetic;
- admission gates;
- approval state transitions;
- audit-log writing;
- retention and deletion enforcement.

---

## 7. End-to-end workflow

```text
1. Define market and decision question
2. Validate domain-pack and collection configuration
3. Estimate provider and model cost
4. Approve or automatically admit run within budget
5. Collect consumer-query signals
6. Collect SERP observations
7. Collect governed GERP observations
8. Persist raw payloads and hashes
9. Parse and normalise observations
10. Resolve brands, products, attributes and sources
11. Perform automated data-quality checks
12. Calculate visibility, recommendation and source metrics
13. Detect candidate gaps using versioned rules
14. Retrieve supporting evidence
15. Retrieve counter-evidence
16. Apply admission gates
17. Calculate opportunity scores and confidence
18. Generate evidence-linked explanation
19. Run evaluation and policy checks
20. Create Draft Opportunity Card
21. Analyst evidence review
22. Domain reviewer challenge
23. Approve, Watchlist or Reject
24. Assign owner and proposed action
25. Publish to governed dashboard
26. Monitor freshness, outcomes and drift
27. Re-evaluate, resolve or expire
28. Feed labelled decisions into evaluation curation
```

### 7.1 Mandatory opportunity admission gates

A candidate cannot enter analyst review unless it has:

- at least two independent signal families, such as demand plus SERP gap, or demand plus GERP omission;
- valid evidence lineage;
- no critical data-quality failure;
- sample-size and confidence labels;
- freshness within its configured policy;
- counter-evidence search completed or explicitly marked unavailable;
- no unresolved entity ambiguity above the allowed threshold;
- score and rule versions;
- no policy or budget breach.

A candidate must be automatically rejected or quarantined when evidence is fabricated, lineage is broken, required fields are absent, or a critical security control fails.

---

## 8. Data architecture and contracts

### 8.1 Storage model

- **PostgreSQL:** configuration metadata, normalised observations, entities, metrics, candidates, reviews, decisions and audit records.
- **S3-compatible object storage:** immutable raw payloads, exports, large trace payloads and evaluation artefacts.
- **Redis:** short-lived caching, rate-control state and initial worker queues. Redis is not the system of record.
- **Telemetry backend:** OpenTelemetry Collector with a supported logs, metrics and traces backend.

### 8.2 Principal data entities

- `CollectionRun`
- `Observation`
- `RawArtifact`
- `EvidenceItem`
- `Entity`
- `EntityAlias`
- `ConsumerNeed`
- `ProductAttribute`
- `BrandMention`
- `Recommendation`
- `Exclusion`
- `SourceCitation`
- `MetricResult`
- `GapCandidate`
- `CounterEvidence`
- `OpportunityScore`
- `OpportunityCard`
- `ReviewDecision`
- `EvaluationRun`
- `PolicyDecision`
- `AgentRun`
- `AuditEvent`

### 8.3 Data contract requirements

Each produced dataset requires:

- named owner;
- semantic definition;
- schema and compatibility policy;
- required fields;
- uniqueness rules;
- freshness objective;
- accepted null policy;
- quality checks;
- classification and retention;
- producer and consumer list;
- change notification process;
- sample record;
- version.

### 8.4 Missing-data policy

Missing, unavailable, blocked and genuinely zero values are different states. The system must never convert missing evidence into zero demand, zero visibility or zero recommendation by default.

Allowed states:

```text
OBSERVED_ZERO
OBSERVED_VALUE
NOT_COLLECTED
PROVIDER_ERROR
PARSING_FAILED
NOT_APPLICABLE
SUPPRESSED_BY_POLICY
INSUFFICIENT_SAMPLE
```

---

## 9. SERP–GERP analytical model

### 9.1 Consumer demand signals

Potential signals include:

- query topics and modifiers;
- search volume where contractually available;
- related queries and questions;
- intent class;
- attribute combinations;
- market, language and device;
- trend and seasonality;
- trade-buyer versus consumer intent;
- recurring problem statements.

### 9.2 SERP dimensions

- organic visibility;
- paid presence where available;
- shopping and product-result presence;
- source type;
- domain diversity;
- brand diversity;
- rank distribution;
- answer-feature presence;
- content freshness;
- retailer versus manufacturer balance;
- concentration using HHI;
- volatility across repeated observations.

### 9.3 GERP dimensions

- primary recommendation;
- supporting recommendation;
- mere mention;
- explicit exclusion;
- brand and product presence;
- need and attribute coverage;
- cited source;
- citation support;
- answer consistency across repeat runs;
- model/provider coverage;
- prompt and model version.

A mention must not be counted as a recommendation. An excluded product must not be counted positively.

### 9.4 Gap families

- high demand with weak SERP supply;
- high demand with weak GERP recommendation coverage;
- visible in SERP but absent from GERP;
- recommended by GERP but poorly supported by searchable evidence;
- need or attribute with no dominant supplying brand;
- market-language gap;
- source-authority gap;
- contradictory recommendation gap;
- emerging need with low current competition;
- complementary-product or service gap;
- information gap that HKTDC could address through content, events or supplier discovery.

### 9.5 Hidden-opportunity score

The final score is deterministic and decomposable:

```text
Opportunity Score =
  0.30 × Demand Strength
+ 0.20 × SERP Supply Gap
+ 0.20 × GERP Recommendation Gap
+ 0.15 × Strategic Relevance
+ 0.10 × Feasibility
+ 0.05 × Evidence Confidence
− Risk Penalties
```

Weights are starting defaults, not universal truth. They must be versioned, reviewed with HKTDC stakeholders and tested against labelled analyst decisions.

Risk penalties may include:

- stale evidence;
- low sample size;
- high cross-run instability;
- unresolved entity ambiguity;
- strong counter-evidence;
- market-size uncertainty;
- regulatory or safety concern;
- concentration illusion caused by provider coverage.

### 9.6 Statistical presentation rules

- every proportion shows `n` and a confidence interval;
- rates with very small samples are labelled exploratory;
- repeated GERP observations are required before claiming recommendation stability;
- market comparisons use equivalent collection settings;
- no causal claim is made from observational SERP–GERP association;
- threshold and weight sensitivity is available during review;
- confidence is kept separate from estimated business value.

---

## 10. Evaluation and continuous delivery for AI

### 10.1 Evaluation layers

**Component evaluation**

- entity-resolution precision and recall;
- recommendation precision and recall;
- exclusion-detection accuracy;
- evidence-span accuracy;
- citation-support rate;
- attribute agreement;
- schema-valid output rate.

**Workflow evaluation**

- unsupported-claim rate;
- false-opportunity rate;
- counter-evidence recall;
- cross-run stability;
- end-to-end replay success;
- analyst acceptance and override rate.

**Platform evaluation**

- run success rate;
- p50 and p95 latency;
- cost per observation and Opportunity Card;
- trace completeness;
- policy-violation rate;
- mean time to detect and recover;
- self-service completion rate.

### 10.2 Evaluation datasets

Maintain versioned sets for:

- brand and product entity resolution;
- recommendation versus mention versus exclusion;
- need and attribute extraction;
- citation grounding;
- counter-evidence;
- candidate admission;
- Opportunity Card quality;
- prompt-injection resistance;
- malformed and adversarial provider payloads.

Dataset partitions:

```text
Development set → visible to builders
Validation set  → used by release pipeline
Holdout set     → controlled by evaluation owner
Production challenge set → curated from real failures and disputes
```

### 10.3 Promotion policy

A new model, prompt, parser, rule or rubric must:

1. pass unit, integration, contract and security tests;
2. pass schema validity requirements;
3. run against the appropriate golden set;
4. compare against the production champion;
5. remain within metric regression tolerances;
6. run in shadow mode where production risk warrants it;
7. receive required owner approval;
8. support rollback to the previous approved version.

Example quality ratchet:

```yaml
recommendation_extraction:
  primary_metric: primary_recommendation_precision
  minimum: 0.90
  maximum_regression: 0.01
  secondary_metrics:
    evidence_span_accuracy: 0.90
    exclusion_recall: 0.85
    schema_validity: 0.995

opportunity_generation:
  false_opportunity_rate_max: 0.10
  unsupported_claim_rate_max: 0.02
  human_approval_required: true
```

Thresholds become binding only after validation on a sufficiently representative labelled set.

### 10.4 Production feedback loop

```text
Production trace
→ Analyst review or dispute
→ Label and root-cause classification
→ Evaluation curation queue
→ Dataset-owner approval
→ New regression case
→ Candidate-version evaluation
→ Controlled promotion
```

Production data must not be added automatically to a golden set without quality and privacy checks.

---

## 11. AI-native observability

### 11.1 Telemetry model

Use OpenTelemetry-compatible logs, metrics and traces. One discovery run forms a parent trace with child spans:

```text
Opportunity Discovery Run
├── Configuration validation
├── Cost estimation
├── Query collection
├── SERP collection
│   ├── Provider submission
│   ├── Polling
│   └── Parsing
├── GERP collection
│   ├── Prompt rendering
│   ├── Model call
│   └── Citation extraction
├── Entity resolution
├── Data-quality checks
├── Gap detection
├── Counter-evidence
├── Scoring
├── Evaluation
└── Human review event
```

### 11.2 Required span attributes

- trace, span, run and tenant identifiers;
- capability and agent version;
- market and domain pack;
- provider task identifier;
- model and prompt version;
- rule, schema and score version;
- token usage and cost;
- latency and retry count;
- evidence identifiers;
- quality and policy status;
- error classification;
- human-review decision reference.

Sensitive prompts and payloads are not placed directly in unrestricted telemetry. Store protected payloads separately and reference them by authorised identifiers.

### 11.3 Operational alerts

Alerts include:

- provider failure or abnormal latency;
- budget threshold exceeded;
- repeated schema-validation failure;
- missing trace sections;
- stale data;
- sudden entity-resolution degradation;
- unsupported-claim spike;
- recommendation-distribution shift;
- excessive retry or agent-loop behaviour;
- dead-letter queue growth;
- unusual outbound network attempt;
- review backlog breaching service targets.

---

## 12. Security, privacy and responsible AI

### 12.1 Identity and access

- integrate with Microsoft Entra ID where available;
- use role-based access initially and attribute-based restrictions for sensitive markets or datasets where needed;
- assign distinct workload identity to every deployed service;
- avoid shared human credentials;
- maintain short-lived credentials where supported;
- separate development, test and production identities;
- perform quarterly access review and immediate offboarding revocation.

### 12.2 Agent-specific security controls

- deny-by-default tool access;
- per-agent capability manifest;
- strict input and output schemas;
- network egress allowlist;
- private-IP and SSRF protection;
- prompt-injection detection tests;
- untrusted content labelling;
- instruction/data separation;
- maximum step count, runtime and spend;
- loop detection;
- tool-argument validation;
- agent-to-agent delegation audit;
- human approval for irreversible actions;
- emergency kill switch;
- capability revocation without redeploying the entire platform.

### 12.3 Data protection

- classify raw and derived data;
- minimise personal data collection;
- redact secrets and sensitive values from logs;
- encrypt in transit and at rest;
- define retention by evidence type and provider terms;
- protect raw payload access separately from aggregate dashboard access;
- record purpose and legal/contractual basis where applicable;
- support deletion or restricted processing when required;
- review cross-border storage and provider contractual requirements before production rollout.

### 12.4 Supply-chain security

- pinned dependency versions;
- dependency and secret scanning;
- container-image scanning;
- software bill of materials;
- signed release artefacts where supported;
- protected branches and mandatory review;
- provenance for deployed images and configuration;
- periodic restore and incident exercises.

### 12.5 Responsible-AI requirements

Every published Opportunity Card states:

- what the system observed;
- what it inferred;
- what it does not know;
- supporting and counter-evidence;
- confidence and sample information;
- known limitations;
- human decision and owner;
- next validation action.

---

## 13. Golden path and escape hatches

### 13.1 Golden path

The approved default journey is:

```text
Validated domain pack
→ Cost estimate
→ Governed collection
→ Immutable raw evidence
→ Contract validation
→ Deterministic metrics
→ Candidate admission
→ Counter-evidence
→ Scoring
→ Evaluation
→ Human approval
→ Governed publication
```

A new market should be onboarded by configuration and validation rather than core-code modification.

### 13.2 Control levels

```yaml
mandatory:
  - evidence_lineage
  - schema_validation
  - audit_log
  - secrets_management
  - trace_context
  - cost_budget
  - human_approval_for_high_priority

recommended_but_overridable:
  - default_model
  - clustering_method
  - worker_implementation
  - dashboard_visualisation

governed_extension_points:
  - provider_adapter
  - model_adapter
  - domain_taxonomy
  - market_configuration
  - custom_gap_rule
  - evaluator
  - exporter
```

Overrides require an owner, rationale, expiry or review date, test evidence and explicit assumption of operational responsibility.

---

## 14. Streamlit dashboard specification

### Page 1: Executive Opportunity Portfolio

- priority Opportunity Cards;
- portfolio by market, need, attribute and status;
- confidence versus estimated value;
- new, persistent, declining and resolved opportunities;
- review and action ownership.

### Page 2: Consumer Need Explorer

- query and need clusters;
- intent distribution;
- attribute combinations;
- market and language filters;
- trend, sample size and freshness.

### Page 3: SERP Landscape

- visibility by brand and source type;
- feature coverage;
- rank distribution;
- concentration and volatility;
- weak-supply areas.

### Page 4: GERP Recommendation Landscape

- primary, supporting, mention and exclusion rates;
- recommendation consistency;
- model and prompt coverage;
- citation-support status;
- brand and attribute gaps.

### Page 5: SERP–GERP Gap Matrix

- demand versus SERP supply;
- demand versus GERP coverage;
- SERP-visible but GERP-absent items;
- GERP recommendations with weak supporting evidence;
- threshold and sensitivity controls for authorised analysts.

### Page 6: Opportunity Evidence Room

- raw and normalised evidence;
- source spans;
- counter-evidence;
- score decomposition;
- sample size and interval;
- versions and trace link;
- Approve, Watchlist and Reject actions.

### Page 7: Platform Health and Governance

- run health, latency and failures;
- data freshness and quality;
- provider and model cost;
- evaluation trends;
- policy exceptions;
- review backlog;
- version adoption and rollback status.

Dashboard rules:

- no KPI without definition and observation period;
- no rate without sample size;
- no opportunity without confidence, evidence and status;
- missing values remain visibly missing;
- authorised users can reach evidence and trace detail from every Opportunity Card;
- aggregate views respect access controls.

---

## 15. Platform operating model

### 15.1 Roles

- **Executive Sponsor:** owns strategic mandate and funding.
- **Platform Product Owner:** owns roadmap, adoption and platform outcomes.
- **Platform Engineering Team:** owns runtime, APIs, registry, observability and reliability.
- **Data Engineering Team:** owns collection, contracts, transformations and quality.
- **AI/Evaluation Team:** owns model gateway, prompts, evaluations and quality ratchets.
- **Domain Product Owner:** owns opportunity definitions and business acceptance.
- **Domain Stewards:** own taxonomy, brands, attributes and market interpretation.
- **Security and Privacy Owner:** owns threat model, access and incident requirements.
- **Analyst Review Board:** challenges and approves material opportunities.
- **Streamlit Product Team:** owns dashboard usability and accessibility.
- **SRE/Operations Owner:** owns service targets, incidents, backup and recovery.

### 15.2 RACI highlights

- Platform Product Owner approves reusable platform roadmap.
- Domain Product Owner approves business rules and score interpretation.
- Evaluation Owner approves golden-set changes and release thresholds.
- Security Owner approves production threat model and critical exceptions.
- Analyst Review Board approves high-priority Opportunity Cards.
- Platform Engineering cannot unilaterally redefine domain opportunity logic.
- Domain users cannot bypass mandatory security, lineage or audit controls.

### 15.3 Platform product metrics

- time to first successful sandbox run;
- time to onboard a market;
- time to add a provider adapter;
- time to create and test a gap rule;
- percentage of runs using the golden path;
- monthly active analysts;
- self-service task completion rate;
- support requests per 100 runs;
- reusable capability adoption;
- deployment frequency and change-failure rate;
- mean time to restore;
- analyst trust, acceptance and override rates;
- unit cost per observation and reviewed opportunity.

---

## 16. Developer and analyst experience

### 16.1 Repository structure

```text
platform/
├── api/
├── workflow_runtime/
├── model_gateway/
├── evidence_service/
├── capability_registry/
├── policy_engine/
├── evaluation/
├── observability/
└── common_contracts/

products/opportunity_intelligence/
├── gap_detection/
├── counter_evidence/
├── scoring/
├── opportunity_lifecycle/
└── dashboard/

domain_packs/sports_footwear/
├── markets/
├── taxonomy/
├── brands/
├── attributes/
├── prompts/
├── rules/
├── scoring/
└── evaluation_sets/

infrastructure/
├── containers/
├── environments/
├── telemetry/
├── security/
└── backup/

docs/
├── tutorials/
├── how-to/
├── reference/
├── explanation/
├── adr/
└── runbooks/
```

### 16.2 Documentation standard

Adopt Diátaxis:

- **Tutorials:** first sandbox run, first Opportunity Card;
- **How-to guides:** add a market, inspect a trace, test a rule, recover a run;
- **Reference:** APIs, CLI, schemas, metrics, permissions and configurations;
- **Explanation:** evidence model, scoring philosophy, architecture and agent boundaries.

Target onboarding benchmark:

> A new authorised engineer or analyst can validate the domain pack, run a sandbox sample, inspect its trace and open a Draft Opportunity Card within 60 minutes using documentation only.

---

## 17. Service levels and resilience

Initial service objectives:

- control API monthly availability: 99.5%;
- scheduled-pipeline success: at least 95%, excluding documented third-party outages;
- trace completeness: at least 99% of production runs;
- recovery-point objective: 24 hours for analytical metadata;
- recovery-time objective: 8 hours for the initial release;
- critical security incident acknowledgement: within 30 minutes during supported hours;
- failed high-priority run triage: within one business day;
- review of stale high-priority Opportunity Cards: within five business days of alert.

Resilience controls:

- database backup and tested restore;
- object-store versioning where supported;
- infrastructure and configuration version control;
- rollback procedure;
- dead-letter queue and replay;
- provider circuit breaker;
- graceful model fallback or abstention;
- documented degraded operating mode;
- quarterly recovery exercise.

---

## 18. Delivery roadmap

### Phase 0: Mobilisation and baseline, Weeks 1–2

Deliverables:

- scope, users and decision-right boundaries;
- current v3.0 architecture inventory;
- target architecture and ADRs;
- ownership and RACI;
- threat-model workshop;
- baseline cost and quality metrics;
- prioritised backlog.

Exit criteria:

- named owners;
- approved Level 2 scope;
- production-data handling decision;
- measurable baseline.

### Phase 1: Platform foundation, Weeks 3–6

Deliverables:

- repository separation;
- Pydantic and JSON Schema contracts;
- capability and configuration registries;
- evidence service;
- model gateway skeleton;
- identity, secrets and environment separation;
- OpenTelemetry trace context;
- CI quality gates.

Exit criteria:

- one end-to-end walking skeleton;
- immutable evidence persisted;
- trace reaches all major services;
- unauthorised tool and network calls denied.

### Phase 2: Level 2 analytical product, Weeks 7–11

Deliverables:

- query, SERP and GERP pipelines;
- entity resolution;
- evidence and counter-evidence extraction;
- deterministic metrics and gap rules;
- scoring engine;
- Opportunity Card lifecycle;
- initial Streamlit pages.

Exit criteria:

- representative sports-footwear sample processed;
- candidate gates enforced;
- all cards trace to evidence;
- missing-data semantics validated.

### Phase 3: Evaluation and safety, Weeks 12–15

Deliverables:

- golden datasets;
- component and workflow metrics;
- champion-challenger comparison;
- prompt-injection and malformed-input tests;
- agent budgets and kill switch;
- shadow-mode release workflow;
- production feedback curation process.

Exit criteria:

- quality thresholds met or exceptions formally recorded;
- rollback demonstrated;
- high-priority cards require human approval;
- initial security test findings resolved or accepted by owner.

### Phase 4: Self-service and full dashboard, Weeks 16–19

Deliverables:

- governed CLI and API;
- seven Streamlit pages;
- analyst review workflow;
- documentation following Diátaxis;
- cost preview and trace inspection;
- platform-health dashboard.

Exit criteria:

- onboarding benchmark completed by a new user;
- analyst can run, inspect, review and export without engineering intervention;
- access boundaries tested.

### Phase 5: Production readiness and pilot, Weeks 20–24

Deliverables:

- service objectives and alerts;
- runbooks and incident response;
- backup and restore test;
- SBOM and release provenance;
- load, resilience and recovery tests;
- controlled HKTDC pilot;
- lessons-learned and prioritised post-pilot backlog.

Exit criteria:

- operational readiness review passed;
- pilot users trained;
- production support owners assigned;
- go-live decision recorded.

---

## 19. Testing strategy

Required test layers:

1. unit tests for deterministic logic;
2. schema and configuration tests;
3. data-contract tests;
4. provider-adapter contract tests using recorded fixtures;
5. agent structured-output tests;
6. golden-dataset evaluation;
7. end-to-end workflow tests;
8. permission and policy tests;
9. prompt-injection and adversarial-input tests;
10. load, timeout and retry tests;
11. failure-recovery and replay tests;
12. backup and restore tests;
13. dashboard accessibility and role tests;
14. user-acceptance tests with analysts;
15. shadow and rollback tests.

No release may bypass mandatory tests without a time-bound, owner-approved exception recorded in the audit system.

---

## 20. Definition of Done

The Level 2 platform release is done only when:

- platform, product and domain-pack layers are separate;
- all production capabilities have owners and versions;
- contracts validate input, output and configuration;
- every published opportunity has evidence and counter-evidence status;
- metrics are deterministic and reproducible;
- trace context covers the complete workflow;
- logs exclude secrets and protected payloads;
- policies enforce tool, network, time, step and cost limits;
- evaluation thresholds and rollback are operational;
- human review is enforced for high-priority outputs;
- Streamlit provides all seven governed views;
- self-service CLI/API supports the golden path;
- backup, restore and incident runbooks are tested;
- data retention and provider-use requirements are documented;
- security and operational-readiness reviews pass;
- pilot acceptance criteria are met;
- known limitations and residual risks are recorded.

---

## 21. Improvements from v3.0

### 21.1 Summary of material improvements

| Area | v3.0 position | v4.0 improvement | Result |
|---|---|---|---|
| Product architecture | Strong domain application | Separates platform, product and domain pack | Reusable beyond running shoes |
| Platform ownership | Mainly technical delivery | Adds product owner, service owners and RACI | Clear accountability |
| Self-service | Mostly opportunity APIs | Adds governed CLI/API journeys and cost preview | Lower dependence on central team |
| Golden path | Implicit workflow | Defines approved end-to-end path | Faster, safer onboarding |
| Escape hatches | Not explicit | Defines mandatory, overridable and extensible controls | Flexibility without losing governance |
| Capability management | Modules and folders | Adds capability registry, owners, permissions and SLOs | Discoverable and governable reuse |
| Agent safety | General security controls | Adds identity, tool allowlists, egress, budgets, step limits and kill switch | Lower agentic risk and cost exposure |
| Observability | Compatible logging | Adds full traces, spans, attributes, alerts and payload separation | End-to-end diagnosis and auditability |
| Evaluation | Golden sets and metrics | Adds quality ratchets, champion-challenger, shadow, rollback and feedback loop | Continuous delivery for AI |
| Model access | Agent-level model calling | Adds governed model gateway | Central budget, policy and audit control |
| Data contracts | Versioned schemas | Adds ownership, compatibility, null semantics and producer/consumer contracts | Safer change management |
| Missing data | Recognised concept | Adds explicit missingness states | Prevents false zero and false opportunities |
| Security | RBAC, secrets, SSRF, scanning | Adds agent-specific threat controls and supply-chain provenance | Enterprise-grade defence in depth |
| Human governance | Review workflow | Adds decision boundaries, named owners and review board | Stronger accountability |
| DevEx | Repository and tooling | Adds Diátaxis, onboarding benchmark and domain-pack workflow | Measurable developer experience |
| Resilience | Backup, rollback and runbook | Adds SLOs, RPO/RTO, graceful degradation and recovery exercises | Operable service, not just deployable code |
| Dashboard | Opportunity-focused design | Adds seven-page governed dashboard including platform health | Business and operational transparency |
| Platform metrics | Technical and analytical KPIs | Adds adoption, self-service, unit-cost and support-load measures | Platform-as-a-product management |
| Release governance | CI/CD awareness | Adds formal promotion states and exception process | Controlled production change |
| Extensibility | DataForSEO-centred implementation | Adds provider, model, evaluator and exporter adapters | Reduces provider lock-in |

### 21.2 Why these improvements matter

#### Improvement 1: Platform core is separated from domain logic

Without separation, the system can only be maintained as a running-shoe application. The new architecture permits HKTDC to retain evidence, evaluation, review, observability and security services while replacing only the domain pack.

#### Improvement 2: Agents become governed capabilities

An agent name is not an operational contract. v4.0 gives every capability an owner, schema, permissions, service target, cost model and lifecycle state, making reuse and incident ownership possible.

#### Improvement 3: AI operations become traceable end to end

Plain logs cannot reliably reconstruct a multi-agent execution. v4.0 correlates provider calls, model calls, evidence, rules, evaluations and human decisions under one trace.

#### Improvement 4: Evaluation controls deployment

v3.0 specified useful evaluation metrics, but v4.0 connects them to release decisions through quality ratchets, champion-challenger comparison, shadow execution and rollback.

#### Improvement 5: Agent-specific security is explicit

Traditional RBAC and secrets are insufficient for systems that can call tools repeatedly. v4.0 limits each agent by capability, network destination, steps, time, spend and delegation.

#### Improvement 6: Self-service is safe and measurable

v4.0 allows analysts and engineers to validate a domain pack, estimate cost, launch a governed run, inspect evidence and run evaluations without waiting for the platform team, while retaining policy and audit controls.

#### Improvement 7: Missing data cannot silently become a business signal

Explicit missingness states prevent provider failure or collection gaps from being interpreted as absent demand, weak competition or brand vacuum.

#### Improvement 8: Platform success is measured as a product

The plan now measures onboarding time, self-service completion, adoption, support load, reusable capability use and unit cost in addition to model quality.

#### Improvement 9: Production feedback improves future releases

Analyst rejection, dispute and failure cases enter a governed curation queue, turning production experience into regression tests without automatically contaminating the golden set.

#### Improvement 10: HKTDC decisions remain human-accountable

The system can detect and explain an opportunity, but named reviewers remain responsible for approval, external communication and action.

---

## 22. Prioritised implementation backlog

### P0: Required before production pilot

- three-layer architecture and repository separation;
- evidence service and immutable lineage;
- validated schemas and domain-pack contracts;
- governed model gateway;
- end-to-end trace context;
- capability identity and deny-by-default tool access;
- cost, time and step limits;
- deterministic scoring and admission gates;
- golden evaluation suite and release gate;
- human approval for high-priority output;
- Streamlit Evidence Room and Platform Health pages;
- backup, restore, rollback and incident runbooks.

### P1: Required for enterprise-scale adoption

- self-service CLI and API;
- capability registry user interface;
- full seven-page dashboard;
- shadow and champion-challenger workflows;
- domain-pack onboarding template;
- Diátaxis documentation;
- adoption and unit-cost metrics;
- workload identity and advanced policy automation;
- full production-feedback curation workflow.

### P2: Add when reuse justifies investment

- multi-provider routing;
- mature internal capability marketplace;
- policy-as-code expansion;
- advanced attribute-based access;
- automated experiment allocation;
- multi-domain portfolio comparison;
- migration to a more durable workflow engine if operational evidence supports it.

The team must avoid building a large marketplace or complex orchestration layer before two or more real domain products demonstrate the need.

---

## 23. Key risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Provider coverage bias | False market conclusions | Record provider scope, compare samples, show limitations |
| Unstable generative answers | Inconsistent opportunity signals | Repeated runs, version capture, stability metrics |
| Mention treated as recommendation | Inflated brand presence | Separate primary, supporting, mention and exclusion labels |
| Missing data treated as zero | False hidden opportunities | Explicit missingness states and admission gates |
| Entity-resolution error | Wrong brand or product attribution | Confidence threshold, alias registry, human review |
| Agent loop or excessive calls | Cost and availability incident | Step, time, budget and concurrency limits |
| Prompt injection in retrieved content | Tool misuse or corrupted output | Untrusted-content handling, allowlists and adversarial tests |
| Overfitting to analyst preferences | Narrow or biased opportunities | Holdout sets, reviewer diversity and documented rubrics |
| Dashboard confidence illusion | Overconfident decision-making | Show evidence, sample size, intervals and limitations |
| Platform overengineering | Delayed business value | Walking skeleton, phased delivery and evidence-based P2 investment |
| Provider or model lock-in | Higher cost and migration difficulty | Adapter contracts and evidence stored in provider-neutral form |
| Unclear ownership | Slow incidents and stale logic | Capability owners, RACI and service targets |

---

## 24. Recommended immediate next actions

1. Freeze v3.0 as the baseline and create v4.0 architecture decision records.
2. Split the repository into platform, opportunity product and sports-footwear domain pack.
3. Define the first five contracts: Collection Request, Observation, Evidence Item, Gap Candidate and Opportunity Card.
4. Implement a walking skeleton for one market, one device, one SERP provider and one governed GERP model.
5. Add trace propagation before adding further agents.
6. Build the first labelled evaluation set for recommendation, mention, exclusion and evidence support.
7. Implement agent capability manifests, budgets and egress allowlists.
8. Build Streamlit Opportunity Portfolio, Evidence Room and Platform Health pages first.
9. Run a controlled analyst pilot, record disputes and calibrate thresholds.
10. Approve production security, operational readiness and data-retention requirements before go-live.

---

## 25. Final acceptance statement

This v4.0 plan is designed to meet enterprise AI platform expectations through reusable services, strong evidence lineage, platform-as-a-product ownership, governed self-service, bounded agents, continuous evaluation, AI-native observability, security-by-design, human accountability and production operations.

It does not claim that architecture documentation alone makes the system enterprise-grade. Enterprise readiness is achieved only when the stated controls are implemented, tested, measured and accepted through the Definition of Done and production-readiness review.
