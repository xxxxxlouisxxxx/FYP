"""Validation of the Opportunity Intelligence sections of a domain pack (rules, gates, scoring, ratchet)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from hop.platform.common_contracts import Contract, SignalFamily
from hop.platform.domain_registry import DomainPack, DomainPackError
from hop.products.opportunity_intelligence import PRODUCT_ID

Op = Literal[">=", "<=", ">", "<", "==", "!="]
SCORE_COMPONENTS = (
    "demand_strength",
    "serp_supply_gap",
    "gerp_recommendation_gap",
    "strategic_relevance",
    "feasibility",
    "evidence_confidence",
)


class Condition(Contract):
    metric: str
    op: Op
    value: float
    field: Literal["value", "rate", "ci_low", "ci_high"] = "value"


class RuleTestCase(Contract):
    name: str
    metrics: dict[str, float | None]
    expected: bool


class GapRule(Contract):
    rule_id: str = Field(pattern=r"^[a-z0-9_]+$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    gap_family: str
    scope: Literal["need", "brand"]
    description: str
    signal_families: list[SignalFamily] = Field(min_length=1)
    all_of: list[Condition] = Field(min_length=1)
    tests: list[RuleTestCase] = Field(default_factory=list)
    enabled: bool = True


class GapRuleSet(Contract):
    rule_set_id: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    owner: str
    status: Literal["draft", "tested", "approved", "deprecated", "retired"]
    rules: list[GapRule] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> GapRuleSet:
        ids = [r.rule_id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule_id in rule set")
        return self


class GapRulesFile(Contract):
    rule_sets: list[GapRuleSet] = Field(min_length=1)


class AdmissionPolicy(Contract):
    version: str
    owner: str
    min_signal_families: int = Field(ge=2, description="spec 7.1 requires at least two independent families")
    max_entity_ambiguity_rate: float = Field(ge=0, le=1)
    require_counter_evidence: bool = True
    min_sample_n: int = Field(ge=1)
    require_rule_and_score_versions: bool = True
    critical_quality_flags: list[str] = Field(default_factory=list)


class PenaltyRule(Contract):
    penalty_id: str
    label: str
    amount: float = Field(ge=0, le=0.5)
    condition: Condition
    apply_when_missing: bool = True


class PriorityThresholds(Contract):
    high: float = Field(gt=0, le=1)
    medium: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _order(self) -> PriorityThresholds:
        if self.medium >= self.high:
            raise ValueError("medium threshold must be below high")
        return self


class ScoringRubric(Contract):
    score_version: str = Field(pattern=r"^score-v\d+\.\d+\.\d+$")
    owner: str
    weights: dict[str, float]
    penalties: list[PenaltyRule]
    priority_thresholds: PriorityThresholds

    @model_validator(mode="after")
    def _weights(self) -> ScoringRubric:
        if set(self.weights) != set(SCORE_COMPONENTS):
            raise ValueError(f"weights must define exactly {list(SCORE_COMPONENTS)}")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be non-negative")
        if abs(sum(self.weights.values()) - 1.0) > 1e-9:
            raise ValueError(f"weights must sum to 1.0 (got {sum(self.weights.values()):.4f})")
        return self


class Ratchet(Contract):
    primary_metric: str
    minimum: float
    maximum_regression: float
    secondary_metrics: dict[str, float] = Field(default_factory=dict)


class QualityRatchetFile(Contract):
    version: str
    owner: str
    ratchets: dict[str, Any]
    champion: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def ratchet(self, key: str) -> Ratchet:
        return Ratchet.model_validate(self.ratchets[key])


@dataclass
class OpportunityConfig:
    rule_sets: dict[str, GapRuleSet]
    admission: AdmissionPolicy
    scoring: ScoringRubric
    ratchet: QualityRatchetFile

    @property
    def active_rule_set(self) -> GapRuleSet:
        approved = [r for r in self.rule_sets.values() if r.status == "approved"]
        if not approved:
            raise ValueError("no approved gap rule set")
        return sorted(approved, key=lambda r: tuple(int(x) for x in r.version.split(".")))[-1]


def load_opportunity_config(pack: DomainPack) -> OpportunityConfig:
    ext = pack.extensions.get(PRODUCT_ID)
    if ext is None:
        raise DomainPackError([f"domain pack {pack.pack_id} does not install {PRODUCT_ID}"])
    errors: list[str] = []

    def v(model: type[Contract], key: str) -> Any:
        try:
            return model.model_validate(ext.get(key))
        except ValidationError as exc:
            for err in exc.errors():
                errors.append(f"{PRODUCT_ID}.{key}: {'.'.join(str(p) for p in err['loc'])}: {err['msg']}")
            return None

    rules = v(GapRulesFile, "gap_rules")
    admission = v(AdmissionPolicy, "admission_gates")
    scoring = v(ScoringRubric, "scoring")
    ratchet = v(QualityRatchetFile, "quality_ratchet")
    if rules is not None:
        for rs in rules.rule_sets:
            for rule in rs.rules:
                if rule.scope == "need" and len(rule.signal_families) > 3:
                    errors.append(f"rule {rule.rule_id}: too many signal families")
    if ratchet is not None:
        for key in ("recommendation_extraction", "entity_resolution"):
            try:
                ratchet.ratchet(key)
            except (KeyError, ValidationError) as exc:
                errors.append(f"{PRODUCT_ID}.quality_ratchet: {key}: {exc}")
    if errors:
        raise DomainPackError(errors)
    return OpportunityConfig(
        rule_sets={r.rule_set_id: r for r in rules.rule_sets}, admission=admission, scoring=scoring, ratchet=ratchet
    )
