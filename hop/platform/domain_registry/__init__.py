"""Domain-pack registry (spec 5.5). A domain pack is validated configuration, not code.

The platform validates the generic parts (markets, entities, taxonomy, attributes, queries, sources,
prompts, evaluation suites). Product-specific sections are declared under ``extensions`` and are
validated by the owning product.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from hop.platform.common_contracts import Contract, Device, canonical_json, sha256_hex
from hop.platform.model_gateway import PromptTemplate


class LocaleConfig(Contract):
    locale: str
    language: str
    provider_language_code: str


class TierConfig(Contract):
    description: str
    query_sets: list[str] = Field(min_length=1)
    gerp_repeats: int = Field(ge=1, le=10)
    max_budget_usd: float = Field(gt=0)


class MarketConfig(Contract):
    code: str = Field(pattern=r"^[A-Z]{2}$")
    name: str
    enabled: bool = True
    locales: list[LocaleConfig] = Field(min_length=1)
    default_language: str
    devices: list[Device] = Field(min_length=1)
    default_device: Device
    provider_location_code: int
    currency: str
    timezone: str
    freshness_policy_days: int = Field(ge=1, le=365)
    demand_reference_volume: int = Field(gt=0, description="monthly volume that maps to demand index 1.0")
    tiers: dict[str, TierConfig]

    @model_validator(mode="after")
    def _check(self) -> MarketConfig:
        langs = {loc.language for loc in self.locales}
        if self.default_language not in langs:
            raise ValueError(f"default_language {self.default_language} not in locales {sorted(langs)}")
        if self.default_device not in self.devices:
            raise ValueError("default_device must be one of devices")
        return self

    def locale_for(self, language: str | None) -> LocaleConfig:
        language = language or self.default_language
        for loc in self.locales:
            if loc.language == language:
                return loc
        raise KeyError(f"market {self.code} has no locale for language {language}")


class MarketsFile(Contract):
    version: str
    markets: list[MarketConfig]


class EntityAlias(Contract):
    alias: str = Field(min_length=1)
    language: str = "en"
    ambiguous: bool = False
    case_sensitive: bool = False
    context_patterns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ambiguous_needs_context(self) -> EntityAlias:
        if self.ambiguous and not self.context_patterns:
            raise ValueError(f"ambiguous alias '{self.alias}' requires context_patterns to ever resolve")
        return self


class Entity(Contract):
    entity_id: str = Field(pattern=r"^[a-z0-9_]+$")
    entity_type: str = "brand"
    name: str
    aliases: list[EntityAlias] = Field(min_length=1)
    products: list[str] = Field(default_factory=list)
    origin: str | None = None
    domains: list[str] = Field(default_factory=list)


class EntitiesFile(Contract):
    version: str
    entities: list[Entity]


class NeedNode(Contract):
    need_id: str = Field(pattern=r"^[a-z0-9_]+$")
    label: dict[str, str]
    parent: str | None = None
    intent_class: str
    attributes: list[str] = Field(default_factory=list)
    match_terms: list[str] = Field(default_factory=list, description="terms that indicate on-need supply")
    strategic_relevance: float = Field(ge=0, le=1)
    feasibility: float = Field(ge=0, le=1)
    regulatory_flags: list[str] = Field(default_factory=list)
    description: str = ""


class TaxonomyFile(Contract):
    version: str
    needs: list[NeedNode]


class AttributeConcept(Contract):
    attribute_id: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str
    category: str
    synonyms: list[str] = Field(default_factory=list)


class AttributesFile(Contract):
    version: str
    attributes: list[AttributeConcept]


class QuerySpec(Contract):
    query_id: str = Field(pattern=r"^[a-z0-9_]+$")
    text: str
    language: str
    need_id: str
    markets: list[str] = Field(min_length=1)
    query_sets: list[str] = Field(min_length=1)
    intent: str

    def applies_to(self, market: str) -> bool:
        return "*" in self.markets or market in self.markets


class QueriesFile(Contract):
    version: str
    queries: list[QuerySpec]


class SourceRule(Contract):
    domain: str
    source_type: str


class SourcesFile(Contract):
    version: str
    source_types: list[str]
    rules: list[SourceRule]

    @model_validator(mode="after")
    def _check(self) -> SourcesFile:
        unknown = {r.source_type for r in self.rules} - set(self.source_types)
        if unknown:
            raise ValueError(f"unknown source types {sorted(unknown)}")
        return self


class PromptsFile(Contract):
    version: str
    prompts: list[PromptTemplate]


class EvaluationSuite(Contract):
    suite_id: str
    version: str
    task: str
    dataset: str
    partition: str = Field(pattern=r"^(development|validation|holdout|production_challenge)$")
    owner: str
    ratchet_key: str
    description: str = ""


class EvaluationSuitesFile(Contract):
    version: str
    suites: list[EvaluationSuite]


class PackManifest(Contract):
    pack_id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    owner: str
    description: str = ""
    platform_compat: str
    files: dict[str, str]
    extensions: dict[str, dict[str, str]] = Field(default_factory=dict)

    @field_validator("files")
    @classmethod
    def _required(cls, files: dict[str, str]) -> dict[str, str]:
        required = {
            "markets",
            "entities",
            "taxonomy",
            "attributes",
            "queries",
            "sources",
            "prompts",
            "evaluation_suites",
        }
        missing = required - files.keys()
        if missing:
            raise ValueError(f"pack manifest missing files: {sorted(missing)}")
        return files


class DomainPackError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class DomainPack:
    root: Path
    manifest: PackManifest
    markets: dict[str, MarketConfig]
    entities: list[Entity]
    needs: dict[str, NeedNode]
    attributes: dict[str, AttributeConcept]
    queries: list[QuerySpec]
    sources: SourcesFile
    prompts: dict[str, PromptTemplate]
    evaluation_suites: dict[str, EvaluationSuite]
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    content_hash: str = ""
    file_versions: dict[str, str] = field(default_factory=dict)

    @property
    def pack_id(self) -> str:
        return self.manifest.pack_id

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def sandbox_dir(self) -> Path | None:
        rel = self.manifest.files.get("sandbox_fixtures")
        return self.root / rel if rel else None

    def market(self, code: str) -> MarketConfig:
        if code not in self.markets:
            raise KeyError(f"market {code} not configured in domain pack {self.pack_id}")
        return self.markets[code]

    def queries_for(self, market: str, tier: str, language: str | None = None) -> list[QuerySpec]:
        m = self.market(market)
        if tier not in m.tiers:
            raise KeyError(f"tier {tier} not configured for market {market}")
        sets = set(m.tiers[tier].query_sets)
        langs = {loc.language for loc in m.locales}
        return [
            q
            for q in self.queries
            if q.applies_to(market)
            and sets & set(q.query_sets)
            and q.language in langs
            and (language is None or q.language == language)
        ]

    def source_type(self, domain: str) -> str:
        domain = domain.lower().removeprefix("www.")
        for rule in self.sources.rules:
            d = rule.domain.lower().removeprefix("www.")
            if domain == d or domain.endswith("." + d):
                return rule.source_type
        return "other"

    def prompt(self, prompt_id: str) -> PromptTemplate:
        return self.prompts[prompt_id]


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _validate(model: type[Contract], path: Path, errors: list[str], label: str) -> Any:
    try:
        return model.model_validate(_load_yaml(path))
    except FileNotFoundError:
        errors.append(f"{label}: file not found {path}")
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            errors.append(f"{label}: {loc}: {err['msg']}")
    except yaml.YAMLError as exc:
        errors.append(f"{label}: invalid YAML: {exc}")
    return None


def pack_dir(packs_root: Path, pack_id: str) -> Path:
    candidates = [packs_root / pack_id, packs_root / pack_id.replace("-", "_")]
    for c in candidates:
        if (c / "pack.yaml").exists():
            return c
    raise DomainPackError([f"domain pack '{pack_id}' not found under {packs_root}"])


def load_domain_pack(packs_root: Path, pack_id: str) -> DomainPack:
    root = pack_dir(packs_root, pack_id)
    errors: list[str] = []
    manifest = _validate(PackManifest, root / "pack.yaml", errors, "pack.yaml")
    if manifest is None:
        raise DomainPackError(errors)
    f = manifest.files
    markets = _validate(MarketsFile, root / f["markets"], errors, "markets")
    entities = _validate(EntitiesFile, root / f["entities"], errors, "entities")
    taxonomy = _validate(TaxonomyFile, root / f["taxonomy"], errors, "taxonomy")
    attributes = _validate(AttributesFile, root / f["attributes"], errors, "attributes")
    queries = _validate(QueriesFile, root / f["queries"], errors, "queries")
    sources = _validate(SourcesFile, root / f["sources"], errors, "sources")
    prompts = _validate(PromptsFile, root / f["prompts"], errors, "prompts")
    suites = _validate(EvaluationSuitesFile, root / f["evaluation_suites"], errors, "evaluation_suites")
    extensions: dict[str, dict[str, Any]] = {}
    for product, files in manifest.extensions.items():
        extensions[product] = {}
        for key, rel in files.items():
            try:
                extensions[product][key] = _load_yaml(root / rel)
            except FileNotFoundError:
                errors.append(f"extensions.{product}.{key}: file not found {rel}")
    if errors:
        raise DomainPackError(errors)

    need_ids = {n.need_id for n in taxonomy.needs}
    attr_ids = {a.attribute_id for a in attributes.attributes}
    _dupes("need_id", [n.need_id for n in taxonomy.needs], errors)
    _dupes("attribute_id", [a.attribute_id for a in attributes.attributes], errors)
    _dupes("entity_id", [e.entity_id for e in entities.entities], errors)
    _dupes("query_id", [q.query_id for q in queries.queries], errors)
    _dupes("market code", [m.code for m in markets.markets], errors)
    for n in taxonomy.needs:
        if n.parent and n.parent not in need_ids:
            errors.append(f"taxonomy: need {n.need_id} parent {n.parent} unknown")
        for a in n.attributes:
            if a not in attr_ids:
                errors.append(f"taxonomy: need {n.need_id} references unknown attribute {a}")
    market_codes = {m.code for m in markets.markets}
    all_sets = {s for q in queries.queries for s in q.query_sets}
    for q in queries.queries:
        if q.need_id not in need_ids:
            errors.append(f"queries: {q.query_id} references unknown need {q.need_id}")
        for m in q.markets:
            if m != "*" and m not in market_codes:
                errors.append(f"queries: {q.query_id} references unknown market {m}")
    for m in markets.markets:
        for tier_id, tier in m.tiers.items():
            for s in tier.query_sets:
                if s not in all_sets:
                    errors.append(f"markets: {m.code} tier {tier_id} references unknown query_set {s}")
    alias_owner: dict[str, str] = {}
    for e in entities.entities:
        for a in e.aliases:
            key = a.alias if a.case_sensitive else a.alias.lower()
            if key in alias_owner and alias_owner[key] != e.entity_id and not a.ambiguous:
                errors.append(
                    f"entities: alias '{a.alias}' maps to both {alias_owner[key]} and {e.entity_id}; mark it ambiguous"
                )
            alias_owner.setdefault(key, e.entity_id)
    _dupes("prompt_id", [p.prompt_id for p in prompts.prompts], errors)
    for s in suites.suites:
        if not (root / s.dataset).exists():
            errors.append(f"evaluation_suites: {s.suite_id} dataset not found {s.dataset}")
    if errors:
        raise DomainPackError(errors)

    content = {
        rel: (root / rel).read_text(encoding="utf-8")
        for rel in sorted(
            list(f.values()) + [r for files in manifest.extensions.values() for r in files.values()] + ["pack.yaml"]
        )
        if (root / rel).is_file()
    }
    return DomainPack(
        root=root,
        manifest=manifest,
        markets={m.code: m for m in markets.markets},
        entities=entities.entities,
        needs={n.need_id: n for n in taxonomy.needs},
        attributes={a.attribute_id: a for a in attributes.attributes},
        queries=queries.queries,
        sources=sources,
        prompts={p.prompt_id: p for p in prompts.prompts},
        evaluation_suites={s.suite_id: s for s in suites.suites},
        extensions=extensions,
        content_hash=sha256_hex(canonical_json(content)),
        file_versions={
            "markets": markets.version,
            "entities": entities.version,
            "taxonomy": taxonomy.version,
            "attributes": attributes.version,
            "queries": queries.version,
            "sources": sources.version,
            "prompts": prompts.version,
        },
    )


def _dupes(label: str, values: list[str], errors: list[str]) -> None:
    seen: set[str] = set()
    for v in values:
        if v in seen:
            errors.append(f"duplicate {label}: {v}")
        seen.add(v)


def add_market(packs_root: Path, pack_id: str, market: MarketConfig, *, dry_run: bool = False) -> Path:
    """Onboard a market by configuration; the pack is re-validated and the change rolled back if invalid."""
    root = pack_dir(packs_root, pack_id)
    manifest = PackManifest.model_validate(_load_yaml(root / "pack.yaml"))
    path = root / manifest.files["markets"]
    original = path.read_text(encoding="utf-8")
    data = yaml.safe_load(original)
    if any(m["code"] == market.code for m in data["markets"]):
        raise DomainPackError([f"market {market.code} already exists"])
    data["markets"].append(market.model_dump(mode="json"))
    if dry_run:
        return path
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        load_domain_pack(packs_root, pack_id)
    except DomainPackError:
        path.write_text(original, encoding="utf-8")
        raise
    return path
