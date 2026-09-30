"""``hop`` command-line interface (spec 15)."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from hop.bootstrap import App, ConfigurationError, build_app
from hop.platform.common_contracts import CollectionRequest, ReviewAction, RunStatus
from hop.platform.domain_registry import DomainPackError, LocaleConfig, MarketConfig, add_market, load_domain_pack
from hop.platform.observability import span_tree
from hop.platform.policy_engine import PolicyViolation
from hop.platform.settings import Settings

console = Console(width=int(os.environ.get("HOP_CLI_WIDTH", "140")), height=60)
app = typer.Typer(help="HKTDC Hidden Opportunity Discovery Platform (walking skeleton).", no_args_is_help=True)
domain_app = typer.Typer(help="Domain packs.", no_args_is_help=True)
market_app = typer.Typer(help="Markets in a domain pack.", no_args_is_help=True)
collection_app = typer.Typer(help="Collection runs (the spec 7 discovery workflow).", no_args_is_help=True)
run_app = typer.Typer(help="Workflow runs.", no_args_is_help=True)
trace_app = typer.Typer(help="OpenTelemetry traces.", no_args_is_help=True)
evaluation_app = typer.Typer(help="Evaluation harness.", no_args_is_help=True)
rule_app = typer.Typer(help="Gap rules.", no_args_is_help=True)
opp_app = typer.Typer(help="Opportunity Cards.", no_args_is_help=True)
cap_app = typer.Typer(help="Capability registry.", no_args_is_help=True)
runtime_app = typer.Typer(help="Runtime controls.", no_args_is_help=True)
schema_app = typer.Typer(help="Contract JSON Schemas.", no_args_is_help=True)
audit_app = typer.Typer(help="Audit log.", no_args_is_help=True)
for sub, name in [
    (domain_app, "domain"), (market_app, "market"), (collection_app, "collection"), (run_app, "run"),
    (trace_app, "trace"), (evaluation_app, "evaluation"), (rule_app, "rule"), (opp_app, "opportunity"),
    (cap_app, "capability"), (runtime_app, "runtime"), (schema_app, "schema"), (audit_app, "audit"),
]:  # fmt: skip
    app.add_typer(sub, name=name)

DEFAULT_USER = os.environ.get("HOP_USER", "local.analyst")
DEFAULT_ROLE = os.environ.get("HOP_ROLE", "analyst")
PRIORITY_STYLE = {"HIGH": "bold red", "MEDIUM": "yellow", "LOW": "dim"}
STATUS_STYLE = {"SUCCEEDED": "green", "FAILED": "red", "RUNNING": "cyan", "PENDING": "dim", "SKIPPED": "dim"}


@lru_cache(maxsize=1)
def get_app() -> App:
    return build_app(Settings.from_env())


def fail(message: str, code: int = 1) -> None:
    console.print(f"[bold red]error:[/] {message}")
    raise typer.Exit(code)


def enforce(user: str, role: str, permission: str) -> None:
    try:
        get_app().platform.policy.enforce_permission(user, role, permission)
    except PolicyViolation as exc:
        fail(f"permission denied: {exc.decision.reason}", 3)


def brief(summary: dict[str, Any], limit: int = 110) -> str:
    parts = []
    for k, v in summary.items():
        if k in ("matrix", "lines", "needs", "capabilities_checked"):
            continue
        if isinstance(v, dict):
            v = ", ".join(f"{a}={b}" for a, b in v.items())
            if not v:
                continue
        elif isinstance(v, list):
            v = ",".join(map(str, v))
        parts.append(f"{k}={v}")
    text = "; ".join(parts)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# domain ---------------------------------------------------------------------------------------
@domain_app.command("validate")
def domain_validate(pack_id: str = typer.Argument("sports-footwear", help="Domain pack id")) -> None:
    """Validate a domain pack (schemas, cross-references, product rules, gap-rule tests)."""
    from hop.products.opportunity_intelligence.config import load_opportunity_config
    from hop.products.opportunity_intelligence.gap_detection import run_rule_tests

    settings = Settings.from_env()
    try:
        pack = load_domain_pack(settings.domain_packs_dir, pack_id)
        config = load_opportunity_config(pack)
    except DomainPackError as exc:
        console.print(f"[bold red]Domain pack {pack_id} is INVALID[/] ({len(exc.errors)} error(s))")
        for err in exc.errors:
            console.print(f"  - {err}")
        raise typer.Exit(1) from exc
    reports = [run_rule_tests(rs) for rs in config.rule_sets.values()]
    table = Table(title=f"Domain pack {pack.pack_id} v{pack.version}", show_header=True)
    table.add_column("Section")
    table.add_column("Content")
    table.add_row(
        "Markets", ", ".join(f"{m.code} ({'/'.join(loc.language for loc in m.locales)})" for m in pack.markets.values())
    )
    table.add_row(
        "Brands / aliases",
        f"{len(pack.entities)} / {sum(len(e.aliases) for e in pack.entities)} "
        f"({sum(a.ambiguous for e in pack.entities for a in e.aliases)} ambiguous)",
    )
    table.add_row("Needs / attributes / queries", f"{len(pack.needs)} / {len(pack.attributes)} / {len(pack.queries)}")
    table.add_row("Prompts", ", ".join(f"{p.prompt_id}@{p.version}" for p in pack.prompts.values()))
    table.add_row(
        "Gap rule sets",
        ", ".join(
            f"{r.rule_set_id}@{r.version} \\[{r.status}] ({len(r.rules)} rules)" for r in config.rule_sets.values()
        ),
    )
    table.add_row(
        "Rule tests",
        ", ".join(f"{r.rule_set_id}: {sum(x['passed'] for x in r.results)}/{len(r.results)}" for r in reports),
    )
    table.add_row("Scoring", f"{config.scoring.score_version} weights={config.scoring.weights}")
    table.add_row(
        "Admission policy",
        f"v{config.admission.version}: >= {config.admission.min_signal_families} families, "
        f"ambiguity <= {config.admission.max_entity_ambiguity_rate:.0%}, n >= {config.admission.min_sample_n}",
    )
    table.add_row("Evaluation suites", ", ".join(pack.evaluation_suites))
    table.add_row(
        "Sandbox fixtures", str(pack.sandbox_dir.relative_to(settings.domain_packs_dir)) if pack.sandbox_dir else "none"
    )
    table.add_row("Content hash", pack.content_hash[:16])
    console.print(table)
    if not all(r.passed for r in reports):
        for r in reports:
            for res in r.results:
                if not res["passed"]:
                    console.print(f"  [red]rule test failed[/] {res['rule_id']}: {res['test']} ({res['detail']})")
        raise typer.Exit(1)
    console.print(f"[bold green]Domain pack {pack.pack_id} is valid.[/]")


# market ---------------------------------------------------------------------------------------
@market_app.command("add")
def market_add(
    code: str = typer.Option(..., help="ISO 3166 alpha-2 market code, e.g. MY"),
    name: str = typer.Option(..., help="Display name"),
    locale: list[str] = typer.Option(..., help="language=locale=provider_language_code, e.g. en=en-MY=en"),
    location_code: int = typer.Option(..., help="DataForSEO location code"),
    currency: str = typer.Option(...),
    timezone: str = typer.Option(...),
    reference_volume: int = typer.Option(5000, help="Monthly volume mapped to demand index 1.0"),
    freshness_days: int = typer.Option(30),
    template: str = typer.Option("SG", help="Copy tiers and devices from this market"),
    pack_id: str = typer.Option("sports-footwear", "--pack"),
    dry_run: bool = typer.Option(False, help="Validate without writing"),
) -> None:
    """Add a market to a domain pack (validated; rolled back if the pack becomes invalid)."""
    settings = Settings.from_env()
    pack = load_domain_pack(settings.domain_packs_dir, pack_id)
    tpl = pack.market(template)
    locales = []
    for spec in locale:
        try:
            lang, loc, provider_lang = spec.split("=")
        except ValueError:
            fail(f"--locale must look like en=en-MY=en (got {spec!r})")
        locales.append(LocaleConfig(language=lang, locale=loc, provider_language_code=provider_lang))
    market = MarketConfig(
        code=code.upper(), name=name, locales=locales, default_language=locales[0].language, devices=tpl.devices,
        default_device=tpl.default_device, provider_location_code=location_code, currency=currency, timezone=timezone,
        freshness_policy_days=freshness_days, demand_reference_volume=reference_volume, tiers=tpl.tiers,
    )  # fmt: skip
    try:
        path = add_market(settings.domain_packs_dir, pack_id, market, dry_run=dry_run)
    except (DomainPackError, ValueError) as exc:
        fail(str(exc))
    verb = "validated (dry run)" if dry_run else f"added to {path}"
    console.print(
        f"[green]Market {market.code} {verb}.[/] Queries with markets ['*'] now apply; add sandbox "
        f"fixtures under sandbox/{market.code}/ or configure DataForSEO credentials to collect data."
    )


# collection -----------------------------------------------------------------------------------
def _request(
    market: str,
    tier: str,
    language: str | None,
    repeats: int | None,
    budget: float | None,
    approver: str | None,
    provider: str,
    requested_by: str,
    question: str | None,
) -> CollectionRequest:
    a = get_app()
    return CollectionRequest(
        domain_pack=a.pack.pack_id, market=market.upper(), tier=tier.upper(), language=language, gerp_repeats=repeats,
        budget_usd=budget, budget_approved_by=approver, serp_provider=provider, requested_by=requested_by,
        decision_question=question,
    )  # fmt: skip


@collection_app.command("estimate-cost")
def collection_estimate_cost(
    market: str = typer.Option("HK"),
    tier: str = typer.Option("A"),
    language: str | None = typer.Option(None),
    repeats: int | None = typer.Option(None, help="GERP repeats per query (default from tier)"),
    provider: str = typer.Option("auto", help="auto | sandbox | dataforseo"),
) -> None:
    """Estimate the cost of a collection run before any spend."""
    from hop.products.opportunity_intelligence.pipeline import _estimate

    a = get_app()
    try:
        req = _request(market, tier, language, repeats, None, None, provider, DEFAULT_USER, None)
        deps = a.discovery_deps(provider)
        est = _estimate(deps, req)
    except (ConfigurationError, KeyError) as exc:
        fail(str(exc))
    table = Table(title=f"Cost estimate {req.market} tier {req.tier} ({deps.provider_mode})")
    for col in ("Item", "Provider", "Units", "Unit", "Unit cost USD", "Total USD", "Simulated"):
        table.add_column(col, justify="right" if "USD" in col or col == "Units" else "left")
    for line in est.lines:
        table.add_row(
            line.item,
            line.provider,
            f"{line.units:g}",
            line.unit,
            f"{line.unit_cost_usd:.6f}",
            f"{line.total_usd:.4f}",
            "yes" if line.simulated else "no",
        )
    console.print(table)
    style = "green" if est.within_budget else "red"
    console.print(
        f"[{style}]Total ${est.total_usd:.4f} vs budget ${est.budget_usd:.2f} - "
        f"{'within budget' if est.within_budget else 'OVER BUDGET'}[/]"
    )


@collection_app.command("run")
def collection_run(
    market: str = typer.Option("HK"),
    tier: str = typer.Option("A"),
    language: str | None = typer.Option(None),
    repeats: int | None = typer.Option(None, help="GERP repeats per query (default from tier)"),
    budget: float | None = typer.Option(None, help="Run budget in USD (default: tier limit)"),
    budget_approver: str | None = typer.Option(None, help="Named approver for budgets above the tier limit"),
    provider: str = typer.Option("auto", help="auto | sandbox | dataforseo"),
    question: str | None = typer.Option(None, help="Decision question this run supports"),
    force_new: bool = typer.Option(False, help="Start a new run even if an identical request ran today"),
    user: str = typer.Option(DEFAULT_USER, "--user"),
    role: str = typer.Option(DEFAULT_ROLE, "--role"),
    as_json: bool = typer.Option(False, "--json", help="Print the run as JSON"),
) -> None:
    """Run the discovery workflow end to end and create Draft Opportunity Cards."""
    from hop.products.opportunity_intelligence.pipeline import start_discovery

    enforce(user, role, "run:create")
    a = get_app()
    try:
        req = _request(market, tier, language, repeats, budget, budget_approver, provider, user, question)
        deps = a.discovery_deps(provider)
    except (ConfigurationError, KeyError, ValueError) as exc:
        fail(str(exc))
    console.print(
        f"[bold]Starting discovery run[/] market={req.market} tier={req.tier} provider={deps.provider_mode} "
        f"model={a.platform.gateway.default_model} db={a.settings.database_url}"
    )
    run = start_discovery(deps, req, force_new=force_new)
    if as_json:
        console.print_json(run.model_dump_json())
    else:
        _print_run(a, run.run_id)
    if run.status != RunStatus.SUCCEEDED:
        raise typer.Exit(2)


def _print_run(a: App, run_id: str) -> None:
    run = a.platform.runtime.get(run_id)
    if run is None:
        fail(f"run {run_id} not found")
    style = STATUS_STYLE.get(run.status.value, "red")
    console.print(Panel.fit(
        f"run_id      {run.run_id}\nstatus      [{style}]{run.status.value}[/]\ntrace_id    {run.trace_id}\n"
        f"workflow    {run.workflow}@{run.workflow_version}   resumed {run.resumed_count}x\n"
        f"request     {run.request['market']} tier {run.request['tier']} pack {run.request['domain_pack']}\n"
        f"cost        ${run.actual_cost_usd:.4f} actual (simulated in sandbox) / estimate "
        f"${(run.cost_estimate.total_usd if run.cost_estimate else float('nan')):.4f} / budget ${run.budget_usd:.2f}"
        + (f"\nerror       [red]{run.error}[/] ({run.failure_class})" if run.error else ""),
        title="Collection run",
    ))  # fmt: skip
    table = Table(title="Workflow steps", show_lines=False)
    for col in ("#", "Step", "Status", "Attempts", "ms", "Summary"):
        table.add_column(col)
    for i, st in enumerate(run.steps, 1):
        s = st.status.value
        table.add_row(
            str(i),
            st.name,
            f"[{STATUS_STYLE.get(s, 'red')}]{s}[/]" + (" (ckpt)" if st.restored_from_checkpoint else ""),
            str(st.attempts),
            f"{st.duration_ms or 0:.0f}",
            st.error or brief(st.summary),
        )
    console.print(table)
    cards = a.repo.cards(run_id=run_id)
    if cards:
        _cards_table(cards, f"Draft Opportunity Cards ({len(cards)})")
    cands = a.repo.candidates(run_id)
    if cands:
        not_admitted = [c for c in cands if c.admission.value != "ADMITTED"]
        if not_admitted:
            t = Table(title="Gap candidates not admitted (spec 7.1 gates)")
            for col in ("Rule", "Need", "Brand", "Outcome", "Reason"):
                t.add_column(col)
            for c in not_admitted:
                t.add_row(c.rule_id, c.need_id, c.brand_id or "-", c.admission.value, c.admission_reason or "")
            console.print(t)
    console.print(
        f"Next: [cyan]hop run inspect {run_id}[/] | [cyan]hop trace inspect --run {run_id}[/] | "
        f"[cyan]hop opportunity list[/] | dashboard: [cyan]make dashboard[/]"
    )


def _cards_table(cards: list[Any], title: str) -> None:
    table = Table(title=title)
    for col in ("Card", "Priority", "Score", "Confidence", "Status", "Title", "Evidence (+/-)"):
        table.add_column(col)
    for c in cards:
        table.add_row(
            c.card_id,
            f"[{PRIORITY_STYLE[c.priority]}]{c.priority}[/]",
            f"{c.score.total:.3f}",
            c.confidence_label,
            c.status.value,
            c.title,
            f"{len(c.supporting_evidence_ids)}/{len(c.counter_evidence_ids)}",
        )
    console.print(table)


# run ------------------------------------------------------------------------------------------
def _resolve_run(run_id: str) -> str:
    a = get_app()
    if run_id == "latest":
        runs = a.platform.runtime.list_runs(1)
        if not runs:
            fail("no runs yet; try: hop collection run --market HK --tier A")
        return runs[0].run_id
    return run_id


@run_app.command("list")
def run_list(limit: int = typer.Option(20)) -> None:
    """List recent runs."""
    a = get_app()
    table = Table(title="Runs")
    for col in ("Run", "Status", "Market", "Tier", "Created", "Cost USD", "Cards", "Trace"):
        table.add_column(col)
    for r in a.platform.runtime.list_runs(limit):
        table.add_row(
            r.run_id,
            f"[{STATUS_STYLE.get(r.status.value, 'red')}]{r.status.value}[/]",
            r.request.get("market", ""),
            r.request.get("tier", ""),
            r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            f"{r.actual_cost_usd:.4f}",
            str(len(a.repo.cards(run_id=r.run_id))),
            r.trace_id or "",
        )
    console.print(table)


@run_app.command("inspect")
def run_inspect(run_id: str = typer.Argument("latest"), as_json: bool = typer.Option(False, "--json")) -> None:
    """Show a run: steps, costs, candidates and cards."""
    a = get_app()
    rid = _resolve_run(run_id)
    if as_json:
        run = a.platform.runtime.get(rid)
        if run is None:
            fail(f"run {rid} not found")
        console.print_json(run.model_dump_json())
        return
    _print_run(a, rid)
    costs = a.platform.costs.breakdown(rid)
    if costs:
        t = Table(title="Cost records")
        for col in ("Category", "Provider", "Capability", "Units", "Unit", "USD", "Simulated"):
            t.add_column(col)
        for c in costs:
            t.add_row(
                c["category"],
                c["provider"],
                c["capability_id"],
                f"{c['units']:g}",
                c["unit"],
                f"{c['usd']:.6f}",
                str(c["simulated"]),
            )
        console.print(t)


@run_app.command("resume")
def run_resume(
    run_id: str, user: str = typer.Option(DEFAULT_USER, "--user"), role: str = typer.Option(DEFAULT_ROLE, "--role")
) -> None:
    """Resume a failed/killed run from its last checkpoint."""
    from hop.products.opportunity_intelligence.pipeline import resume_discovery

    enforce(user, role, "run:create")
    a = get_app()
    run = a.platform.runtime.get(run_id)
    if run is None:
        fail(f"run {run_id} not found")
    deps = a.discovery_deps(CollectionRequest.model_validate(run.request).serp_provider)
    resume_discovery(deps, run_id)
    _print_run(a, run_id)


@run_app.command("cancel")
def run_cancel(run_id: str, user: str = typer.Option(DEFAULT_USER, "--user")) -> None:
    """Cancel a run (checked between activities)."""
    get_app().platform.runtime.cancel(run_id, user)
    console.print(f"run {run_id} cancelled")


@run_app.command("dead-letters")
def run_dead_letters(limit: int = typer.Option(20)) -> None:
    """Show failed steps in the dead-letter table."""
    rows = get_app().platform.runtime.dead_letters(limit)
    table = Table(title="Dead letters")
    for col in ("Run", "Step", "Failure class", "Error", "At"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["run_id"], r["step"], r["failure_class"], r["error"][:80], r["created_at"])
    console.print(table)


# trace ----------------------------------------------------------------------------------------
@trace_app.command("inspect")
def trace_inspect(
    trace_id: str | None = typer.Argument(None),
    run: str | None = typer.Option(None, "--run", help="Run id (or 'latest') instead of a trace id"),
    max_depth: int = typer.Option(3, help="Collapse spans deeper than this"),
    show_attributes: bool = typer.Option(False, "--attributes"),
) -> None:
    """Print the span tree for a trace (Opportunity Discovery Run and children)."""
    a = get_app()
    if trace_id is None:
        r = a.platform.runtime.get(_resolve_run(run or "latest"))
        if r is None or r.trace_id is None:
            fail("run has no trace")
        trace_id = r.trace_id
    spans = a.platform.telemetry.spans_for_trace(trace_id)
    if not spans:
        fail(f"no spans for trace {trace_id}")
    tree = Tree(f"[bold]trace {trace_id}[/] ({len(spans)} spans)")
    nodes: dict[int, Tree] = {-1: tree}
    hidden: dict[str, int] = {}
    for depth, s in span_tree(spans):
        if depth > max_depth:
            hidden[s["name"]] = hidden.get(s["name"], 0) + 1
            continue
        label = f"{s['name']} [dim]{s['duration_ms']:.1f} ms[/]" + (" [red]ERROR[/]" if s["status"] == "ERROR" else "")
        attrs = s["attributes"]
        extras = [
            f"{k}={attrs[k]}"
            for k in (
                "activity.attempt",
                "retry.count",
                "cost.usd",
                "model.id",
                "query.id",
                "capability.id",
                "model.abstained",
            )
            if k in attrs
        ]
        if extras:
            label += f" [dim]({', '.join(map(str, extras))})[/]"
        if show_attributes:
            label += f"\n[dim]{json.dumps(attrs, default=str)[:300]}[/]"
        nodes[depth] = nodes[depth - 1].add(label)
    console.print(tree)
    if hidden:
        console.print(
            "[dim]collapsed deeper spans: " + ", ".join(f"{k} x{v}" for k, v in sorted(hidden.items())) + "[/]"
        )


# evaluation -----------------------------------------------------------------------------------
@evaluation_app.command("run")
def evaluation_run(
    suite: list[str] = typer.Option(None, "--suite", help="Suite id(s); default all"),
    user: str = typer.Option(DEFAULT_USER, "--user"),
    role: str = typer.Option(DEFAULT_ROLE, "--role"),
) -> None:
    """Run golden-set evaluations and compare against the quality ratchet and champion."""
    from hop.platform.evaluation import EvaluationHarness
    from hop.products.opportunity_intelligence.evaluation import run_suites

    enforce(user, role, "evaluation:run")
    a = get_app()
    harness = EvaluationHarness(a.platform.store, a.platform.telemetry, a.platform.audit)
    results = run_suites(harness, a.platform.gateway, a.pack, a.config, a.resolver, suite or None)
    ok = True
    for r in results:
        ok &= r.passed
        t = Table(
            title=f"{r.suite_id}@{r.suite_version} ({r.partition}, n={r.n_cases}) - "
            + ("[green]PASS[/]" if r.passed else "[red]FAIL[/]")
        )
        for col in ("Check", "Metric", "Observed", "Threshold", "Result"):
            t.add_column(col)
        for c in r.checks:
            obs = "missing" if c["observed"] is None else f"{c['observed']:.4f}"
            t.add_row(
                c["check"],
                c["metric"],
                obs,
                f"{c['op']} {c['threshold']:.4f}",
                "[green]pass[/]" if c["passed"] else "[red]fail[/]",
            )
        console.print(t)
        other = {k: v for k, v in r.metrics.items() if k not in {c["metric"] for c in r.checks}}
        console.print(f"  subject={r.subject} other metrics={other}")
        for f in r.failures[:10]:
            console.print(f"  [red]case failure[/] {f}")
    raise typer.Exit(0 if ok else 1)


# rules ----------------------------------------------------------------------------------------
@rule_app.command("test")
def rule_test(rule_set: str | None = typer.Option(None, "--rule-set")) -> None:
    """Run the unit tests embedded in the gap-rule definitions."""
    from hop.products.opportunity_intelligence.gap_detection import run_rule_tests

    a = get_app()
    ok = True
    for rs in a.config.rule_sets.values():
        if rule_set and rs.rule_set_id != rule_set:
            continue
        report = run_rule_tests(rs)
        ok &= report.passed
        t = Table(title=f"{rs.rule_set_id}@{rs.version} \\[{rs.status}]")
        for col in ("Rule", "Test", "Expected", "Actual", "Result", "Conditions"):
            t.add_column(col)
        for r in report.results:
            t.add_row(
                r["rule_id"],
                r["test"],
                str(r.get("expected")),
                str(r.get("actual")),
                "[green]pass[/]" if r["passed"] else "[red]fail[/]",
                r["detail"],
            )
        console.print(t)
    raise typer.Exit(0 if ok else 1)


# opportunities --------------------------------------------------------------------------------
@opp_app.command("list")
def opportunity_list(
    status: str | None = typer.Option(None),
    market: str | None = typer.Option(None),
    run: str | None = typer.Option(None, "--run"),
) -> None:
    """List Opportunity Cards ordered by score."""
    cards = get_app().repo.cards(status=status, market=market, run_id=_resolve_run(run) if run else None)
    if not cards:
        console.print("no opportunity cards")
        return
    _cards_table(cards, f"Opportunity Cards ({len(cards)})")


@opp_app.command("show")
def opportunity_show(card_id: str, as_json: bool = typer.Option(False, "--json")) -> None:
    """Show one Opportunity Card with its score breakdown, statements and review history."""
    a = get_app()
    card = a.repo.card(card_id)
    if card is None:
        fail(f"card {card_id} not found")
    if as_json:
        console.print_json(card.model_dump_json())
        return
    console.print(
        Panel.fit(
            f"[bold]{card.title}[/]\n{card.card_id}  status {card.status.value}  priority "
            f"{card.priority}  score {card.score.total:.3f}  confidence {card.confidence_label}\n"
            f"{card.explanation.summary}",
            title="Opportunity Card",
        )
    )
    for group in ("observed", "inferred", "unknowns", "limitations"):
        for s in getattr(card, group):
            console.print(f"  [{group.upper()}] {s.text} [dim]{len(s.evidence_ids)} evidence[/]")
    t = Table(title=f"Score breakdown {card.score.score_version}")
    for col in ("Component", "Weight", "Value", "Contribution", "Source"):
        t.add_column(col)
    for comp in card.score.components:
        t.add_row(
            comp.component_id,
            f"{comp.weight:.2f}",
            "missing" if comp.value is None else f"{comp.value:.3f}",
            f"{comp.contribution:.3f}",
            comp.source,
        )
    for p in card.score.penalties:
        if p.applied:
            t.add_row(f"penalty: {p.label}", "", "", f"-{p.amount:.3f}", p.reason)
    console.print(t)
    console.print(f"Next validation action: {card.next_validation_action}")
    for d in a.repo.reviews(card_id):
        console.print(
            f"  review {d.decided_at:%Y-%m-%d %H:%M} {d.reviewer} ({d.reviewer_role}) {d.action.value} "
            f"{d.from_status}->{d.to_status} {d.rationale or ''}"
        )


@opp_app.command("review")
def opportunity_review(
    card_id: str,
    action: ReviewAction = typer.Option(..., case_sensitive=False),
    reviewer: str = typer.Option(DEFAULT_USER),
    role: str = typer.Option(DEFAULT_ROLE),
    rationale: str | None = typer.Option(None),
    owner: str | None = typer.Option(None),
    proposed_action: str | None = typer.Option(None),
) -> None:
    """Move a card through Draft -> In Review -> Approved / Watchlist / Rejected."""
    from hop.products.opportunity_intelligence.opportunity_lifecycle import LifecycleError

    a = get_app()
    try:
        outcome = a.lifecycle.review(
            card_id,
            action,
            reviewer=reviewer,
            role=role,
            rationale=rationale,
            owner=owner,
            proposed_action=proposed_action,
        )
    except LifecycleError as exc:
        fail(str(exc))
    except PolicyViolation as exc:
        fail(f"permission denied: {exc.decision.reason}", 3)
    for d in outcome.decisions:
        console.print(
            f"[green]{d.action.value}[/] {d.from_status} -> {d.to_status} by {d.reviewer} ({d.reviewer_role})"
        )
    console.print(f"card {card_id} is now [bold]{outcome.card.status.value}[/]")


@opp_app.command("approve")
def opportunity_approve(
    card_id: str,
    reviewer: str = typer.Option(DEFAULT_USER),
    role: str = typer.Option(DEFAULT_ROLE),
    owner: str = typer.Option(..., help="Accountable owner"),
    rationale: str | None = typer.Option(None),
    proposed_action: str | None = typer.Option(None),
) -> None:
    """Approve a card (shortcut for review --action APPROVE)."""
    opportunity_review(card_id, ReviewAction.APPROVE, reviewer, role, rationale, owner, proposed_action)


@opp_app.command("export")
def opportunity_export(
    fmt: str = typer.Option("json", "--format", help="json | csv"),
    out: Path | None = typer.Option(None, "--out", help="Also write to this local file"),
    status: str | None = typer.Option(None),
    market: str | None = typer.Option(None),
    user: str = typer.Option(DEFAULT_USER, "--user"),
    role: str = typer.Option(DEFAULT_ROLE, "--role"),
) -> None:
    """Export Opportunity Cards with lineage and versions (governed by opportunity.exporter)."""
    from hop.products.opportunity_intelligence.opportunity_lifecycle.export import export_cards

    if fmt not in ("json", "csv"):
        fail("--format must be json or csv")
    enforce(user, role, "opportunity:read")
    a = get_app()
    cards = a.repo.cards(status=status, market=market)
    uri, data = export_cards(a.platform, cards, fmt=fmt, actor=user, out=out)  # type: ignore[arg-type]
    console.print(
        f"exported {len(cards)} card(s) as {fmt} ({len(data):,} bytes) -> {uri}" + (f" and {out}" if out else "")
    )


# capabilities ---------------------------------------------------------------------------------
@cap_app.command("list")
def capability_list() -> None:
    """List registered capabilities with status, tools and egress allowlist."""
    a = get_app()
    revoked = a.platform.registry.revoked()
    t = Table(title="Capability registry")
    for col in ("Capability", "Version", "Kind", "Status", "Executable", "Tools", "Egress allowlist", "Models"):
        t.add_column(col)
    for m in a.platform.registry.all():
        ok, reason = a.platform.registry.executable_status(m.capability_id, a.settings.env)
        t.add_row(
            m.capability_id,
            m.version,
            m.kind.value,
            m.status.value + (" (REVOKED)" if m.capability_id in revoked else ""),
            "[green]yes[/]" if ok else f"[red]no[/] {reason}",
            ", ".join(m.allowed_tools) or "-",
            ", ".join(m.network_policy.outbound_allowlist) or "-",
            ", ".join(m.model_policy.allowed_models) if m.model_policy else "-",
        )
    console.print(t)


@cap_app.command("revoke")
def capability_revoke(
    capability_id: str,
    reason: str = typer.Option(...),
    user: str = typer.Option(DEFAULT_USER, "--user"),
    role: str = typer.Option(DEFAULT_ROLE, "--role"),
) -> None:
    """Revoke a capability (takes effect immediately for every workflow)."""
    from hop.platform.common_contracts import ActorType

    enforce(user, role, "capability:revoke")
    a = get_app()
    a.platform.registry.revoke(capability_id, reason)
    a.platform.audit.record(
        actor=user,
        actor_type=ActorType.HUMAN,
        action="capability.revoke",
        resource_type="capability",
        resource_id=capability_id,
        details={"reason": reason},
    )
    console.print(f"[yellow]capability {capability_id} revoked[/]: {reason}")


@cap_app.command("reinstate")
def capability_reinstate(
    capability_id: str,
    user: str = typer.Option(DEFAULT_USER, "--user"),
    role: str = typer.Option(DEFAULT_ROLE, "--role"),
) -> None:
    """Reinstate a revoked capability."""
    from hop.platform.common_contracts import ActorType

    enforce(user, role, "capability:revoke")
    a = get_app()
    a.platform.registry.reinstate(capability_id)
    a.platform.audit.record(
        actor=user,
        actor_type=ActorType.HUMAN,
        action="capability.reinstate",
        resource_type="capability",
        resource_id=capability_id,
    )
    console.print(f"[green]capability {capability_id} reinstated[/]")


# runtime --------------------------------------------------------------------------------------
@runtime_app.command("kill-switch")
def runtime_kill_switch(
    state: str = typer.Argument(..., help="on | off | status"),
    reason: str = typer.Option("operator action"),
    user: str = typer.Option(DEFAULT_USER, "--user"),
    role: str = typer.Option(DEFAULT_ROLE, "--role"),
) -> None:
    """Engage or release the global kill switch (stops provider and model calls at the next check)."""
    a = get_app()
    if state == "status":
        console.print(f"kill switch {'[red]ENGAGED[/]' if a.platform.kill_switch.engaged() else '[green]released[/]'}")
        return
    if state not in ("on", "off"):
        fail("state must be on, off or status")
    enforce(user, role, "runtime:kill_switch")
    a.platform.kill_switch.set(state == "on", actor=user, reason=reason)
    from hop.platform.common_contracts import ActorType

    a.platform.audit.record(
        actor=user,
        actor_type=ActorType.HUMAN,
        action=f"runtime.kill_switch.{state}",
        resource_type="runtime",
        resource_id="kill_switch",
        details={"reason": reason},
    )
    console.print(f"kill switch {'[red]ENGAGED[/]' if state == 'on' else '[green]released[/]'} by {user}")


# schema / audit -------------------------------------------------------------------------------
@schema_app.command("export")
def schema_export(out: Path = typer.Option(Path("docs/reference/schemas"), "--out")) -> None:
    """Export JSON Schemas for all published contracts."""
    from hop.schemas import export_schemas

    for path in export_schemas(out):
        console.print(f"wrote {path}")


@audit_app.command("verify")
def audit_verify() -> None:
    """Verify the audit log hash chain."""
    ok, n = get_app().platform.audit.verify_chain()
    console.print(f"audit chain {'[green]valid[/]' if ok else '[red]BROKEN[/]'} ({n} events)")
    raise typer.Exit(0 if ok else 1)


@audit_app.command("list")
def audit_list(resource: str | None = typer.Option(None), limit: int = typer.Option(30)) -> None:
    """Show recent audit events."""
    t = Table(title="Audit events")
    for col in ("When", "Actor", "Type", "Action", "Resource", "Outcome"):
        t.add_column(col)
    for e in get_app().platform.audit.list(resource_id=resource, limit=limit):
        t.add_row(
            e.occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
            e.actor,
            e.actor_type.value,
            e.action,
            f"{e.resource_type}:{e.resource_id}",
            e.outcome,
        )
    console.print(t)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
