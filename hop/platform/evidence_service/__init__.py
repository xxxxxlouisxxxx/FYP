"""Evidence Service: the authoritative link between raw observations and business conclusions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from hop.platform.common_contracts import EvidenceItem, EvidenceType, sha256_hex
from hop.platform.evidence_service.object_store import LocalObjectStore, ObjectStore, ObjectStoreError
from hop.platform.storage.db import EvidenceRow, RawArtifactRow, Store

__all__ = ["EvidenceService", "LineageResult", "LocalObjectStore", "ObjectStore", "RawArtifact"]


@dataclass(frozen=True)
class RawArtifact:
    uri: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class LineageResult:
    evidence_key: str
    valid: bool
    reason: str


class EvidenceService:
    def __init__(self, store: Store, objects: ObjectStore) -> None:
        self.store = store
        self.objects = objects

    # raw payloads -------------------------------------------------------------------------
    def persist_raw(
        self,
        data: bytes,
        *,
        run_id: str | None,
        namespace: str,
        content_type: str = "application/json",
        classification: str = "INTERNAL",
    ) -> RawArtifact:
        digest = sha256_hex(data)
        ext = {"text/csv": "csv", "text/plain": "txt"}.get(content_type, "json")
        key = f"{namespace}/{run_id or 'global'}/{digest}.{ext}"
        uri = self.objects.put(key, data, content_type)
        with self.store.session() as s:
            if s.get(RawArtifactRow, uri) is None:
                s.add(
                    RawArtifactRow(
                        uri=uri,
                        sha256=digest,
                        size_bytes=len(data),
                        content_type=content_type,
                        run_id=run_id,
                        classification=classification,
                    )
                )
        return RawArtifact(uri=uri, sha256=digest, size_bytes=len(data))

    def read_raw(self, uri: str) -> bytes:
        return self.objects.get(uri)

    # evidence records ---------------------------------------------------------------------
    def add(self, item: EvidenceItem) -> EvidenceItem:
        """Idempotent insert. Re-adding an identical record is a no-op; a different one is refused."""
        with self.store.session() as s:
            existing = s.get(EvidenceRow, (item.evidence_id, item.version))
            if existing is not None:
                if existing.record_hash != item.record_hash():
                    raise ValueError(f"evidence {item.key} exists with different content; use correct()")
                return EvidenceItem.model_validate(existing.body)
            s.add(self._row(item))
        return item

    def add_many(self, items: Iterable[EvidenceItem]) -> int:
        count = 0
        for item in items:
            self.add(item)
            count += 1
        return count

    @staticmethod
    def _row(item: EvidenceItem) -> EvidenceRow:
        return EvidenceRow(
            evidence_id=item.evidence_id,
            version=item.version,
            run_id=item.run_id,
            evidence_type=item.evidence_type.value,
            market=item.market,
            need_id=item.need_id,
            content_hash=item.content_hash,
            record_hash=item.record_hash(),
            body=item.model_dump(mode="json"),
        )

    def get(self, evidence_id: str, version: int | None = None) -> EvidenceItem | None:
        with self.store.session() as s:
            q = select(EvidenceRow).where(EvidenceRow.evidence_id == evidence_id)
            q = q.where(EvidenceRow.version == version) if version else q.order_by(EvidenceRow.version.desc())
            row = s.execute(q.limit(1)).scalar()
            return EvidenceItem.model_validate(row.body) if row else None

    def history(self, evidence_id: str) -> list[EvidenceItem]:
        with self.store.session() as s:
            rows = s.execute(
                select(EvidenceRow).where(EvidenceRow.evidence_id == evidence_id).order_by(EvidenceRow.version)
            ).scalars()
            return [EvidenceItem.model_validate(r.body) for r in rows]

    def correct(self, evidence_id: str, *, reason: str, **changes: Any) -> EvidenceItem:
        current = self.get(evidence_id)
        if current is None:
            raise KeyError(evidence_id)
        forbidden = {"evidence_id", "version", "content_hash", "raw_payload_uri"} & changes.keys()
        if forbidden:
            raise ValueError(f"cannot change lineage fields: {sorted(forbidden)}")
        data = current.model_dump()
        data.update(changes)
        data.update(version=current.version + 1, supersedes_version=current.version, correction_reason=reason)
        data.pop("created_at", None)
        new_item = EvidenceItem.model_validate(data)
        with self.store.session() as s:
            s.add(self._row(new_item))
        return new_item

    def search(
        self,
        *,
        run_id: str,
        need_id: str | None = None,
        evidence_types: Iterable[EvidenceType] | None = None,
        attribute_filter: dict[str, Any] | None = None,
        exclude_quarantined: bool = True,
        limit: int = 200,
    ) -> list[EvidenceItem]:
        with self.store.session() as s:
            latest = (
                select(EvidenceRow.evidence_id, func.max(EvidenceRow.version).label("v"))
                .where(EvidenceRow.run_id == run_id)
                .group_by(EvidenceRow.evidence_id)
                .subquery()
            )
            q = select(EvidenceRow).join(
                latest,
                (EvidenceRow.evidence_id == latest.c.evidence_id) & (EvidenceRow.version == latest.c.v),
            )
            if need_id:
                q = q.where(EvidenceRow.need_id == need_id)
            if evidence_types:
                q = q.where(EvidenceRow.evidence_type.in_([t.value for t in evidence_types]))
            rows = s.execute(q.order_by(EvidenceRow.evidence_id)).scalars().all()
        items = [EvidenceItem.model_validate(r.body) for r in rows]
        if exclude_quarantined:
            items = [i for i in items if i.data_quality_status.value != "QUARANTINED"]
        if attribute_filter:
            items = [i for i in items if all(i.attributes.get(k) == v for k, v in attribute_filter.items())]
        return items[:limit]

    def count(self, run_id: str) -> int:
        with self.store.session() as s:
            return (
                s.execute(select(func.count()).select_from(EvidenceRow).where(EvidenceRow.run_id == run_id)).scalar()
                or 0
            )

    # lineage ------------------------------------------------------------------------------
    def verify_lineage(self, evidence_id: str, _cache: dict[str, str] | None = None) -> LineageResult:
        item = self.get(evidence_id)
        if item is None:
            return LineageResult(evidence_id, False, "evidence not found (possible fabrication)")
        cache = _cache if _cache is not None else {}
        try:
            digest = cache.get(item.raw_payload_uri)
            if digest is None:
                digest = sha256_hex(self.objects.get(item.raw_payload_uri))
                cache[item.raw_payload_uri] = digest
        except ObjectStoreError as exc:
            return LineageResult(item.key, False, f"raw payload unavailable: {exc}")
        if digest != item.content_hash:
            return LineageResult(item.key, False, "raw payload hash mismatch")
        with self.store.session() as s:
            row = s.get(EvidenceRow, (item.evidence_id, item.version))
            if row is None or row.record_hash != item.record_hash():
                return LineageResult(item.key, False, "evidence record hash mismatch")
        return LineageResult(item.key, True, "ok")
