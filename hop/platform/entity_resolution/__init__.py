"""Alias-registry entity resolution. Ambiguous matches are flagged, never silently merged."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hop.platform.domain_registry import Entity, EntityAlias


class ResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class Resolution:
    surface: str
    status: ResolutionStatus
    entity_id: str | None
    candidates: tuple[str, ...]
    confidence: float
    reason: str


@dataclass(frozen=True)
class Hit:
    start: int
    end: int
    surface: str
    resolution: Resolution


def _ascii(text: str) -> bool:
    return all(ord(c) < 128 for c in text)


class EntityResolver:
    version = "alias-resolver-1.1.0"

    def __init__(self, entities: list[Entity]) -> None:
        self.entities = {e.entity_id: e for e in entities}
        self._aliases: list[tuple[EntityAlias, str]] = sorted(
            ((a, e.entity_id) for e in entities for a in e.aliases), key=lambda x: -len(x[0].alias)
        )

    def lexicon(self) -> list[dict[str, Any]]:
        seen: set[tuple[str, bool]] = set()
        out = []
        for alias, _ in self._aliases:
            key = (alias.alias, alias.case_sensitive)
            if key not in seen:
                seen.add(key)
                out.append({"alias": alias.alias, "case_sensitive": alias.case_sensitive})
        return out

    def _matches(self, alias: EntityAlias, surface: str) -> bool:
        return alias.alias == surface if alias.case_sensitive else alias.alias.lower() == surface.lower()

    def resolve(self, surface: str, text: str = "", start: int = 0, end: int | None = None) -> Resolution:
        end = start + len(surface) if end is None else end
        owners = [(a, eid) for a, eid in self._aliases if self._matches(a, surface)]
        if not owners:
            return Resolution(surface, ResolutionStatus.UNRESOLVED, None, (), 0.0, "alias not in registry")
        entity_ids = tuple(sorted({eid for _, eid in owners}))
        if len(entity_ids) > 1:
            return Resolution(surface, ResolutionStatus.AMBIGUOUS, None, entity_ids, 0.0, "alias shared by entities")
        alias, eid = owners[0]
        if alias.ambiguous:
            window_after = text[end : end + 40]
            window_before = text[max(0, start - 40) : start]
            for pattern in alias.context_patterns:
                if re.search(pattern, window_after) or re.search(pattern, window_before):
                    return Resolution(surface, ResolutionStatus.RESOLVED, eid, entity_ids, 0.9, f"context '{pattern}'")
            return Resolution(
                surface, ResolutionStatus.AMBIGUOUS, None, entity_ids, 0.3, "ambiguous alias without context"
            )
        return Resolution(surface, ResolutionStatus.RESOLVED, eid, entity_ids, 1.0, "exact alias")

    def scan(self, text: str) -> list[Hit]:
        taken: list[tuple[int, int]] = []
        hits: list[Hit] = []
        for alias, _ in self._aliases:
            flags = 0 if alias.case_sensitive else re.I
            pattern = rf"(?<![\w]){re.escape(alias.alias)}(?![\w])" if _ascii(alias.alias) else re.escape(alias.alias)
            for m in re.finditer(pattern, text, flags):
                if any(m.start() < e and m.end() > s for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                hits.append(Hit(m.start(), m.end(), m.group(0), self.resolve(m.group(0), text, m.start(), m.end())))
        return sorted(hits, key=lambda h: h.start)

    def name(self, entity_id: str | None) -> str:
        if entity_id is None:
            return "(unresolved)"
        e = self.entities.get(entity_id)
        return e.name if e else entity_id
