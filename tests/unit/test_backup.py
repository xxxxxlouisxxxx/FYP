from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

from hop.platform.common_contracts import RunStatus
from tests.conftest import REPO_ROOT, Discovery, make_app, make_settings

spec = importlib.util.spec_from_file_location("hop_backup", REPO_ROOT / "infrastructure" / "backup" / "backup.py")
assert spec and spec.loader
backup_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup_tool)


def test_backup_restore_round_trip(fresh_discovery: Discovery, tmp_path: Path) -> None:
    source = make_settings(fresh_discovery.data_dir)
    out = backup_tool.backup(source, tmp_path / "backups")
    assert backup_tool.verify(out) == []

    target_dir = tmp_path / "restored"
    backup_tool.restore(make_settings(target_dir), out, force=False)
    restored = make_app(target_dir)
    run = restored.platform.runtime.get(fresh_discovery.run.run_id)
    assert run is not None and run.status == RunStatus.SUCCEEDED
    assert restored.platform.audit.verify_chain()[0]
    card = restored.repo.cards(run_id=run.run_id)[0]
    assert all(restored.platform.evidence.verify_lineage(e).valid for e in card.supporting_evidence_ids)


def test_tampered_backup_is_rejected(fresh_discovery: Discovery, tmp_path: Path) -> None:
    out = backup_tool.backup(make_settings(fresh_discovery.data_dir), tmp_path / "backups")
    archive = out / "objects.tar.gz"
    with tarfile.open(archive, "r:gz") as tar:
        members = [(m, tar.extractfile(m).read()) for m in tar.getmembers() if m.isfile()]
    with tarfile.open(archive, "w:gz") as tar:
        for i, (member, data) in enumerate(members):
            payload = data + b" " if i == 0 else data
            member.size = len(payload)

            tar.addfile(member, io.BytesIO(payload))
    assert backup_tool.verify(out)
