"""Append-only hash-chained audit log."""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import select

from hop.platform.common_contracts import ActorType, AuditEvent, canonical_json, sha256_hex
from hop.platform.storage.db import AuditRow, Store

_LOCK = threading.Lock()


def _hash_event(event: AuditEvent) -> str:
    body = event.model_dump(mode="json", exclude={"event_hash"})
    return sha256_hex(canonical_json(body))


class AuditLog:
    def __init__(self, store: Store, tenant_id: str = "hktdc") -> None:
        self.store = store
        self.tenant_id = tenant_id

    def record(
        self,
        *,
        actor: str,
        actor_type: ActorType,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str = "SUCCESS",
        details: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> AuditEvent:
        with _LOCK, self.store.session() as s:
            last = s.execute(select(AuditRow.event_hash).order_by(AuditRow.seq.desc()).limit(1)).scalar()
            draft = AuditEvent(
                actor=actor,
                actor_type=actor_type,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,  # type: ignore[arg-type]
                details=details or {},
                trace_id=trace_id,
                tenant_id=self.tenant_id,
                prev_event_hash=last,
            )
            event = draft.model_copy(update={"event_hash": _hash_event(draft)})
            s.add(
                AuditRow(
                    event_id=event.event_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    trace_id=trace_id,
                    event_hash=event.event_hash,
                    body=event.model_dump(mode="json"),
                )
            )
        return event

    def list(
        self, *, resource_id: str | None = None, trace_id: str | None = None, limit: int = 500
    ) -> list[AuditEvent]:
        with self.store.session() as s:
            q = select(AuditRow).order_by(AuditRow.seq.desc()).limit(limit)
            if resource_id:
                q = q.where(AuditRow.resource_id == resource_id)
            if trace_id:
                q = q.where(AuditRow.trace_id == trace_id)
            return [AuditEvent.model_validate(r.body) for r in s.execute(q).scalars()]

    def verify_chain(self) -> tuple[bool, int]:
        """Returns (valid, events_checked). Detects edited or removed events."""
        with self.store.session() as s:
            rows = s.execute(select(AuditRow).order_by(AuditRow.seq)).scalars().all()
            prev: str | None = None
            for row in rows:
                event = AuditEvent.model_validate(row.body)
                if event.prev_event_hash != prev or _hash_event(event) != event.event_hash:
                    return False, len(rows)
                prev = event.event_hash
            return True, len(rows)
