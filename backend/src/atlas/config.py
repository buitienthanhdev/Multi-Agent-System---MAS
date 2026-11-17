"""Runtime configuration. Secrets are read from environment only and never logged."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv(
        "ATLAS_DATABASE_URL", f"sqlite:///{(BASE_DIR / 'var' / 'atlas.db').as_posix()}"))
    object_store_dir: Path = field(default_factory=lambda: Path(os.getenv(
        "ATLAS_OBJECT_STORE_DIR", str(BASE_DIR / "var" / "objects"))))
    sandbox_state_file: Path = field(default_factory=lambda: Path(os.getenv(
        "ATLAS_SANDBOX_STATE_FILE", str(BASE_DIR / "var" / "sandbox_publisher.json"))))
    # LLM: "ollama:gemma4:12b" (default real local LLM via Ollama), "template" (deterministic fallback), or any LangChain model id.
    llm_model: str = field(default_factory=lambda: os.getenv("ATLAS_LLM_MODEL", "ollama:gemma4:12b"))
    temporal_address: str | None = field(default_factory=lambda: os.getenv("ATLAS_TEMPORAL_ADDRESS") or None)
    temporal_task_queue: str = field(default_factory=lambda: os.getenv("ATLAS_TEMPORAL_TASK_QUEUE", "atlas-missions"))
    langfuse_enabled: bool = field(default_factory=lambda: bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")))
    approval_ttl_minutes: int = field(default_factory=lambda: int(os.getenv("ATLAS_APPROVAL_TTL_MINUTES", "60")))
    lease_seconds: int = field(default_factory=lambda: int(os.getenv("ATLAS_LEASE_SECONDS", "30")))
    fault_sleep_seconds: float = field(default_factory=lambda: float(os.getenv("ATLAS_FAULT_SLEEP_SECONDS", "0")))


def get_settings() -> Settings:
    return Settings()
