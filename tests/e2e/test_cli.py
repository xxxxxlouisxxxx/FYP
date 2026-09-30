from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hop.cli import main as cli
from tests.conftest import point_env_at


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[CliRunner]:
    point_env_at(tmp_path, monkeypatch)
    cli.get_app.cache_clear()
    yield CliRunner()
    cli.get_app.cache_clear()


def invoke(runner: CliRunner, *args: str) -> tuple[int, str]:
    result = runner.invoke(cli.app, list(args))
    return result.exit_code, result.output


def test_domain_validate_and_rule_test(runner: CliRunner) -> None:
    code, out = invoke(runner, "domain", "validate", "sports-footwear")
    assert code == 0, out
    assert "valid" in out.lower()
    code, out = invoke(runner, "rule", "test")
    assert code == 0, out
    assert "fail" not in out.lower().replace("failed_", "")


def test_estimate_run_inspect_and_export(runner: CliRunner, tmp_path: Path) -> None:
    code, out = invoke(runner, "collection", "estimate-cost", "--market", "HK", "--tier", "A")
    assert code == 0, out
    assert "within budget" in out.lower() or "budget" in out.lower()

    code, out = invoke(runner, "collection", "run", "--market", "HK", "--tier", "A", "--json")
    assert code == 0, out
    run = json.loads(out[out.index("{") :])
    assert run["status"] == "SUCCEEDED"

    code, out = invoke(runner, "run", "inspect", run["run_id"])
    assert code == 0 and "gap_detection" in out
    code, out = invoke(runner, "trace", "inspect", "--run", run["run_id"])
    assert code == 0 and "Gap detection" in out
    code, out = invoke(runner, "opportunity", "list")
    assert code == 0 and "DRAFT" in out

    target = tmp_path / "cards.csv"
    code, out = invoke(runner, "opportunity", "export", "--format", "csv", "--out", str(target))
    assert code == 0, out
    assert target.read_text().startswith("card_id,")
    code, out = invoke(runner, "audit", "verify")
    assert code == 0, out


def test_privileged_commands_are_rbac_checked(runner: CliRunner) -> None:
    code, out = invoke(runner, "runtime", "kill-switch", "on", "--role", "analyst")
    assert code == 3, out
    code, _ = invoke(runner, "runtime", "kill-switch", "on", "--role", "platform_engineer", "--user", "ops.eng")
    assert code == 0
    code, out = invoke(runner, "runtime", "kill-switch", "status")
    assert "ENGAGED" in out
    code, _ = invoke(runner, "runtime", "kill-switch", "off", "--role", "platform_engineer", "--user", "ops.eng")
    assert code == 0
    code, out = invoke(runner, "collection", "run", "--market", "HK", "--role", "viewer")
    assert code == 3, out


def test_evaluation_run_passes_ratchet(runner: CliRunner) -> None:
    code, out = invoke(runner, "evaluation", "run")
    assert code == 0, out
    assert "PASS" in out


def test_schema_export(runner: CliRunner, tmp_path: Path) -> None:
    code, out = invoke(runner, "schema", "export", "--out", str(tmp_path / "schemas"))
    assert code == 0, out
    assert len(list((tmp_path / "schemas").glob("*.schema.json"))) == 12
