"""Telemetry facade: OpenTelemetry-style spans to Langfuse when configured. Never raises into business code."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from atlas.config import get_settings
from atlas.security import redact_obj

log = logging.getLogger("atlas.telemetry")
_client: Any = None
_init_failed = False
LOCAL_SPANS: list[dict[str, Any]] = []  # bounded in-process buffer, useful for tests/debug


def _get_client() -> Any:
    global _client, _init_failed
    if _client is not None or _init_failed or not get_settings().langfuse_enabled:
        return _client
    try:
        from langfuse import get_client
        _client = get_client()
    except Exception as e:  # pragma: no cover - depends on env
        _init_failed = True
        log.warning("langfuse init failed: %s", type(e).__name__)
    return _client


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[dict[str, Any]]:
    rec: dict[str, Any] = {"name": name, "attrs": redact_obj(attrs), "start": time.time()}
    lf_cm = None
    try:
        c = _get_client()
        if c is not None:
            lf_cm = c.start_as_current_observation(name=name, as_type="span", metadata=rec["attrs"])
            lf_cm.__enter__()
    except Exception as e:  # telemetry failure must not break business flow
        log.warning("telemetry start failed: %s", type(e).__name__)
        lf_cm = None
    try:
        yield rec
    finally:
        rec["duration_ms"] = int((time.time() - rec["start"]) * 1000)
        LOCAL_SPANS.append(rec)
        del LOCAL_SPANS[:-500]
        if lf_cm is not None:
            try:
                lf_cm.__exit__(None, None, None)
            except Exception as e:
                log.warning("telemetry end failed: %s", type(e).__name__)
