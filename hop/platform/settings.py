"""Runtime settings resolved from environment variables with safe offline defaults."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, SecretStr

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    env: str = "sandbox"
    tenant_id: str = "hktdc"
    data_dir: Path
    database_url: str
    object_store_dir: Path
    domain_packs_dir: Path
    default_domain_pack: str = "sports-footwear"

    serp_provider: str = "auto"
    model_provider: str = "auto"
    dataforseo_login: SecretStr | None = None
    dataforseo_password: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    kill_switch: bool = False
    activity_timeout_s: float = 120.0
    run_timeout_s: float = 1800.0
    max_activity_attempts_per_run: int = 60
    otel_console: bool = False

    @property
    def dataforseo_configured(self) -> bool:
        return bool(self.dataforseo_login and self.dataforseo_password)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)

    @classmethod
    def from_env(cls, **overrides: object) -> Settings:
        data_dir = Path(os.environ.get("HOP_DATA_DIR", REPO_ROOT / "var"))
        values: dict[str, object] = {
            "env": os.environ.get("HOP_ENV", "sandbox"),
            "tenant_id": os.environ.get("HOP_TENANT_ID", "hktdc"),
            "data_dir": data_dir,
            "database_url": os.environ.get("DATABASE_URL", f"sqlite:///{data_dir / 'hop.db'}"),
            "object_store_dir": Path(os.environ.get("HOP_OBJECT_STORE_DIR", data_dir / "objects")),
            "domain_packs_dir": Path(os.environ.get("HOP_DOMAIN_PACKS_DIR", REPO_ROOT / "domain_packs")),
            "default_domain_pack": os.environ.get("HOP_DOMAIN_PACK", "sports-footwear"),
            "serp_provider": os.environ.get("HOP_SERP_PROVIDER", "auto"),
            "model_provider": os.environ.get("HOP_MODEL_PROVIDER", "auto"),
            "dataforseo_login": os.environ.get("DATAFORSEO_LOGIN") or None,
            "dataforseo_password": os.environ.get("DATAFORSEO_PASSWORD") or None,
            "openai_api_key": os.environ.get("OPENAI_API_KEY") or None,
            "openai_base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "kill_switch": _env_bool("HOP_KILL_SWITCH"),
            "otel_console": _env_bool("HOP_OTEL_CONSOLE"),
        }
        values.update(overrides)
        return cls(**values)
