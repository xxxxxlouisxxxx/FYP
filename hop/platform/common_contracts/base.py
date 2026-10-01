"""Shared primitives for all contracts: IDs, clocks, canonical hashing."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

SHA256_PATTERN = r"^[0-9a-f]{64}$"


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON encoding used for every hash in the platform."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def stable_id(prefix: str, *parts: Any, length: int = 20) -> str:
    """Content-derived identifier so that replays and retries are idempotent."""
    return f"{prefix}_{sha256_hex(canonical_json(list(parts)))[:length]}"


class Contract(BaseModel):
    """Base for every published contract: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class FrozenContract(BaseModel):
    """Immutable contract. Corrections must create a new version."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)
