"""Redaction, hashing, untrusted-content handling, audit."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from atlas.models import AuditEvent

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|cookie|authorization)\s*[:=]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
]
_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)\d{9,10}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

INJECTION_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"ignore (all |any )?(previous|prior|above) instructions", r"bỏ qua (mọi|các) (hướng dẫn|chỉ dẫn)",
        r"you are now", r"system prompt", r"approve (all|every|this) action", r"grant (yourself|admin|permission)",
        r"(print|reveal|send|exfiltrate).{0,30}(secret|api key|token|password|env)", r"ATLAS_[A-Z_]*SECRET",
        r"disable (the )?(policy|budget|approval)",
    ]
]


def redact(text: str) -> str:
    out = text
    for p in _SECRET_PATTERNS:
        out = p.sub("[REDACTED_SECRET]", out)
    out = _EMAIL.sub("[REDACTED_EMAIL]", out)
    out = _PHONE.sub("[REDACTED_PHONE]", out)
    return out


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: ("[REDACTED_SECRET]" if re.search(r"(?i)secret|token|password|api_key|cookie", str(k)) else redact_obj(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def detect_injection(text: str) -> list[str]:
    return [p.pattern for p in INJECTION_PATTERNS if p.search(text)]


def wrap_untrusted(source: str, text: str) -> str:
    """External content is data, never instructions."""
    return f"<untrusted_content source={source!r}>\n{text}\n</untrusted_content>"


def audit(s: Session, workspace_id: str, actor: str, event_type: str, data: dict[str, Any] | None = None,
          mission_id: str | None = None) -> None:
    s.add(AuditEvent(workspace_id=workspace_id, mission_id=mission_id, actor=actor, event_type=event_type,
                     data=redact_obj(data or {})))
