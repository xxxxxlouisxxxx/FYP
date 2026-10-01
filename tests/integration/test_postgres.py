from __future__ import annotations

import pytest
from sqlalchemy import inspect, select

from hop.platform.common_contracts import RunStatus
from hop.platform.storage.db import AuditRow, Base, ImmutableRecordError
from tests.conftest import Discovery

pytestmark = pytest.mark.postgres


def test_runs_on_postgres_with_full_schema(fresh_discovery: Discovery) -> None:
    store = fresh_discovery.app.platform.store
    assert store.engine.dialect.name == "postgresql"
    assert set(Base.metadata.tables) <= set(inspect(store.engine).get_table_names())
    assert fresh_discovery.run.status == RunStatus.SUCCEEDED
    assert fresh_discovery.app.repo.cards(run_id=fresh_discovery.run.run_id)


def test_audit_chain_and_append_only_on_postgres(fresh_discovery: Discovery) -> None:
    platform = fresh_discovery.app.platform
    valid, checked = platform.audit.verify_chain()
    assert valid and checked > 0
    with pytest.raises(ImmutableRecordError), platform.store.session() as s:
        row = s.execute(select(AuditRow).limit(1)).scalar_one()
        row.action = "tampered"
        s.flush()


def test_json_bodies_round_trip_on_postgres(fresh_discovery: Discovery) -> None:
    card = fresh_discovery.app.repo.cards(run_id=fresh_discovery.run.run_id)[0]
    again = fresh_discovery.app.repo.card(card.card_id)
    assert again is not None
    assert again.model_dump(mode="json") == card.model_dump(mode="json")
