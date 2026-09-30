"""Product evaluators for the golden sets declared in the domain pack (spec 10.1-10.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hop.platform.common_contracts import EvaluationRun
from hop.platform.domain_registry import DomainPack, EvaluationSuite
from hop.platform.entity_resolution import EntityResolver, ResolutionStatus
from hop.platform.evaluation import EvaluationHarness, EvaluatorOutput, RatchetSpec
from hop.platform.model_gateway import ModelGateway, StandaloneBudget
from hop.products.opportunity_intelligence.config import OpportunityConfig
from hop.products.opportunity_intelligence.normalisation import strongest_label
from hop.products.opportunity_intelligence.schemas import GerpExtractionOutput


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def label_extraction_evaluator(gateway: ModelGateway, pack: DomainPack, resolver: EntityResolver):  # noqa: ANN201
    prompt = pack.prompt("gerp_extraction")
    lexicon = resolver.lexicon()

    def evaluate(dataset: dict[str, Any]) -> EvaluatorOutput:
        cases = dataset["cases"]
        budget = StandaloneBudget(limit_usd=1.0)
        tp_primary = pred_primary = exp_primary = 0
        tp_excl = exp_excl = 0
        exact_pairs = total_pairs = 0
        spans_ok = spans_total = 0
        schema_ok = 0
        inj_ok = inj_total = 0
        false_brands = 0
        failures: list[dict[str, Any]] = []
        model_id = gateway.default_model
        for case in cases:
            text, expected = case["text"], case.get("expected") or {}
            result = gateway.invoke(
                capability_id="evaluation.harness",
                prompt=prompt,
                variables={"answer_text": text, "lexicon": lexicon},
                output_model=GerpExtractionOutput,
                run=budget,
            )
            model_id = result.model_id or model_id
            predicted: dict[str, str] = {}
            if result.ok and result.output is not None:
                schema_ok += 1
                per_brand: dict[str, list[str]] = {}
                for m in result.output["mentions"]:
                    spans_total += 1
                    spans_ok += text[m["start"] : m["end"]] == m["surface"]
                    res = resolver.resolve(m["surface"], text, m["start"], m["end"])
                    if res.status == ResolutionStatus.RESOLVED and res.entity_id:
                        per_brand.setdefault(res.entity_id, []).append(m["label"])
                predicted = {b: strongest_label(labels) for b, labels in per_brand.items()}
            for b, lab in predicted.items():
                if lab == "PRIMARY_RECOMMENDATION":
                    pred_primary += 1
                    tp_primary += expected.get(b) == "PRIMARY_RECOMMENDATION"
                if b not in expected:
                    false_brands += 1
            for b, lab in expected.items():
                total_pairs += 1
                exact_pairs += predicted.get(b) == lab
                exp_primary += lab == "PRIMARY_RECOMMENDATION"
                if lab == "EXCLUSION":
                    exp_excl += 1
                    tp_excl += predicted.get(b) == "EXCLUSION"
            match = predicted == expected
            if "prompt_injection" in case.get("tags", []):
                inj_total += 1
                inj_ok += match
            if not match:
                failures.append(
                    {
                        "case_id": case["id"],
                        "expected": expected,
                        "predicted": predicted,
                        "abstention": result.abstention_reason,
                    }
                )
        metrics = {
            "primary_recommendation_precision": _ratio(tp_primary, pred_primary),
            "primary_recommendation_recall": _ratio(tp_primary, exp_primary),
            "exclusion_recall": _ratio(tp_excl, exp_excl),
            "label_accuracy": _ratio(exact_pairs, total_pairs),
            "evidence_span_accuracy": _ratio(spans_ok, spans_total),
            "schema_validity": _ratio(schema_ok, len(cases)),
            "injection_resistance": _ratio(inj_ok, inj_total),
            "case_exact_match": _ratio(len(cases) - len(failures), len(cases)),
            "false_brand_rate": _ratio(false_brands, max(1, total_pairs)),
        }
        return EvaluatorOutput(
            metrics=metrics,
            n_cases=len(cases),
            failures=failures,
            subject={
                "model_id": model_id or "",
                "prompt": f"{prompt.prompt_id}@{prompt.version}",
                "extractor": "mock-extractor-1.1.0" if model_id == "mock-gerp-1" else model_id or "",
            },
        )

    return evaluate


def entity_resolution_evaluator(resolver: EntityResolver):  # noqa: ANN201
    def evaluate(dataset: dict[str, Any]) -> EvaluatorOutput:
        cases = dataset["cases"]
        tp = pred_resolved = exp_resolved = 0
        amb_ok = amb_total = 0
        correct = 0
        failures = []
        for case in cases:
            text, surface = case["text"], case["surface"]
            start = text.find(surface)
            res = resolver.resolve(surface, text, max(start, 0), max(start, 0) + len(surface))
            exp_status, exp_entity = case["expected_status"], case.get("expected_entity")
            ok = res.status.value == exp_status and res.entity_id == exp_entity
            correct += ok
            if res.status == ResolutionStatus.RESOLVED:
                pred_resolved += 1
                tp += res.entity_id == exp_entity and exp_status == "RESOLVED"
            exp_resolved += exp_status == "RESOLVED"
            if exp_status == "AMBIGUOUS":
                amb_total += 1
                amb_ok += res.status == ResolutionStatus.AMBIGUOUS
            if not ok:
                failures.append(
                    {
                        "case_id": case["id"],
                        "expected": [exp_status, exp_entity],
                        "predicted": [res.status.value, res.entity_id],
                        "reason": res.reason,
                    }
                )
        return EvaluatorOutput(
            metrics={
                "resolution_precision": _ratio(tp, pred_resolved),
                "resolution_recall": _ratio(tp, exp_resolved),
                "ambiguity_flag_recall": _ratio(amb_ok, amb_total),
                "accuracy": _ratio(correct, len(cases)),
            },
            n_cases=len(cases),
            failures=failures,
            subject={"resolver": resolver.version},
        )

    return evaluate


def load_dataset(pack: DomainPack, suite: EvaluationSuite) -> dict[str, Any]:
    path = Path(pack.root) / suite.dataset
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_suites(
    harness: EvaluationHarness,
    gateway: ModelGateway,
    pack: DomainPack,
    config: OpportunityConfig,
    resolver: EntityResolver,
    suite_ids: list[str] | None = None,
) -> list[EvaluationRun]:
    results = []
    for suite in pack.evaluation_suites.values():
        if suite_ids and suite.suite_id not in suite_ids:
            continue
        if suite.task == "gerp_label_extraction":
            evaluator = label_extraction_evaluator(gateway, pack, resolver)
        elif suite.task == "entity_resolution":
            evaluator = entity_resolution_evaluator(resolver)
        else:
            raise ValueError(f"no evaluator for task {suite.task}")
        r = config.ratchet.ratchet(suite.ratchet_key)
        results.append(
            harness.run(
                suite_id=suite.suite_id,
                suite_version=suite.version,
                partition=suite.partition,
                dataset=load_dataset(pack, suite),
                evaluator=evaluator,
                ratchet=RatchetSpec(r.primary_metric, r.minimum, r.maximum_regression, dict(r.secondary_metrics)),
                champion=config.ratchet.champion.get(suite.ratchet_key),
            )
        )
    return results
