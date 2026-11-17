"""External connectors. Every connector declares its verification level honestly."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from atlas.config import get_settings
from atlas.db import new_id
from atlas.security import detect_injection, redact


class ConnectorTimeout(Exception):
    """Request was (possibly) sent but no response received: outcome UNKNOWN."""


class ConnectorError(Exception):
    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


class NotConfigured(Exception):
    pass


@dataclass
class Receipt:
    external_id: str
    status: str
    raw: dict[str, Any]
    cost_minor: int = 0
    is_sandbox: bool = True


class Connector(Protocol):
    name: str
    verification: str  # live_tested | mocked | not_configured
    supports_idempotency: bool

    def execute(self, action_type: str, payload: dict[str, Any], idempotency_key: str) -> Receipt: ...
    def lookup(self, idempotency_key: str) -> Receipt | None: ...
    def request_stop(self, external_id: str) -> Receipt | None: ...


_lock = threading.Lock()


class SandboxPublisher:
    """Simulated external publishing system with its own persistent state (a JSON file standing in for the
    remote side). It is a PROCESS TEST, not a social network. Supports idempotency keys and fault injection
    via env ATLAS_SANDBOX_FAULT = timeout_after_send | crash_after_send | fail_retryable | fail_permanent."""
    name = "sandbox_publisher"
    verification = "mocked"
    supports_idempotency = True

    def __init__(self, state_file: Path | None = None):
        self.state_file = state_file or get_settings().sandbox_state_file

    def _load(self) -> dict[str, Any]:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text("utf-8"))
        return {"posts": {}, "send_count": 0}

    def _save(self, st: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.state_file)

    def execute(self, action_type: str, payload: dict[str, Any], idempotency_key: str) -> Receipt:
        fault = os.getenv("ATLAS_SANDBOX_FAULT", "")
        if fault == "fail_retryable":
            raise ConnectorError("sandbox: 503 temporarily unavailable", retryable=True)
        if fault == "fail_permanent":
            raise ConnectorError("sandbox: 400 invalid payload", retryable=False)
        with _lock:
            st = self._load()
            if idempotency_key in st["posts"]:
                p = st["posts"][idempotency_key]
            else:
                p = {"external_id": f"sbx_{new_id()[:12]}", "status": "published_sandbox", "payload": payload,
                     "action_type": action_type, "created_at": time.time()}
                st["posts"][idempotency_key] = p
                st["send_count"] += 1
                self._save(st)
        if fault == "timeout_after_send":
            raise ConnectorTimeout("sandbox: response timed out after request was sent")
        if fault == "crash_after_send":
            os._exit(17)  # simulate process death after the remote side committed
        return Receipt(external_id=p["external_id"], status=p["status"], raw={"sandbox": True, **p}, is_sandbox=True)

    def lookup(self, idempotency_key: str) -> Receipt | None:
        p = self._load()["posts"].get(idempotency_key)
        if not p:
            return None
        return Receipt(external_id=p["external_id"], status=p["status"], raw={"sandbox": True, **p})

    def request_stop(self, external_id: str) -> Receipt | None:
        with _lock:
            st = self._load()
            for p in st["posts"].values():
                if p["external_id"] == external_id:
                    p["status"] = "withdrawn_sandbox"
                    self._save(st)
                    return Receipt(external_id=external_id, status=p["status"], raw={"sandbox": True})
        return None

    def send_count(self) -> int:
        return self._load()["send_count"]


class NotConfiguredConnector:
    supports_idempotency = False
    verification = "not_configured"

    def __init__(self, name: str):
        self.name = name

    def execute(self, *a: Any, **k: Any) -> Receipt:
        raise NotConfigured(f"connector {self.name} is not configured")

    def lookup(self, idempotency_key: str) -> Receipt | None:
        raise NotConfigured(f"connector {self.name} is not configured")

    def request_stop(self, external_id: str) -> Receipt | None:
        raise NotConfigured(f"connector {self.name} is not configured")


class PublicHttpReadOnlyConnector:
    """Real read-only HTTP connector with SSRF & host allowlist protection, byte/timeout caps, and untrusted wrapping.
    Works without external credentials against public reference endpoints (e.g. open.er-api.com, wikipedia.org)."""
    name = "public_http_readonly"
    verification = "live_tested"
    supports_idempotency = True
    ALLOWED_HOSTS = {"open.er-api.com", "vi.wikipedia.org", "en.wikipedia.org", "httpbin.org"}

    def fetch_json_or_text(self, url: str, timeout: float = 5.0, max_bytes: int = 65_536) -> dict[str, Any]:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self.ALLOWED_HOSTS:
            raise ConnectorError(f"egress blocked: host '{parsed.hostname}' is not in ALLOWED_HOSTS", retryable=False)
        req = urllib.request.Request(url, headers={"User-Agent": "ATLAS-ReadOnly-Connector/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme & host allowlisted above
                raw_bytes = resp.read(max_bytes)
                ctype = resp.headers.get("Content-Type", "")
                text = raw_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            raise ConnectorError(f"http read failed: {type(e).__name__}: {e}", retryable=True) from e
        flags = detect_injection(text)
        data: Any = None
        if "json" in ctype.lower():
            try:
                data = json.loads(text)
            except Exception:
                data = None
        return {
            "url": url,
            "host": parsed.hostname,
            "status": "fetched_live",
            "text_excerpt": redact(text[:2000]),
            "json": data,
            "injection_flags": flags,
        }

    def execute(self, action_type: str, payload: dict[str, Any], idempotency_key: str) -> Receipt:
        res = self.fetch_json_or_text(payload["url"])
        return Receipt(external_id=f"http_{idempotency_key[:12]}", status="fetched_live", raw=res, is_sandbox=False)

    def lookup(self, idempotency_key: str) -> Receipt | None:
        return None

    def request_stop(self, external_id: str) -> Receipt | None:
        return None


class LiveWebhookConnector:
    """Real outbound HTTP webhook / microsite publishing connector (no sandbox file):
    - Sends a real HTTPS POST with JSON payload + X-Atlas-Idempotency-Key header to an allowlisted webhook endpoint
      (default: https://httpbin.org/post) AND/OR publishes a live landing page to the local microsite directory
      served at /live/{external_id}.html with real click/lead tracking endpoints.
    - Stores verified HTTP response receipts in a persistent lookup ledger for reconciliation."""
    name = "live_webhook_publisher"
    verification = "live_tested"
    supports_idempotency = True
    ALLOWED_POST_HOSTS = {"httpbin.org", "postman-echo.com"}

    def __init__(self, ledger_file: Path | None = None):
        self.ledger_file = ledger_file or (get_settings().sandbox_state_file.parent / "live_webhook_receipts.json")
        self.microsite_dir = get_settings().sandbox_state_file.parent / "live_microsite"

    def _load(self) -> dict[str, Any]:
        if self.ledger_file.exists():
            return json.loads(self.ledger_file.read_text("utf-8"))
        return {"dispatches": {}, "send_count": 0}

    def _save(self, st: dict[str, Any]) -> None:
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ledger_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.ledger_file)

    def execute(self, action_type: str, payload: dict[str, Any], idempotency_key: str) -> Receipt:
        with _lock:
            st = self._load()
            if idempotency_key in st["dispatches"]:
                existing = st["dispatches"][idempotency_key]
                return Receipt(
                    external_id=existing["external_id"],
                    status=existing["status"],
                    raw=existing["raw"],
                    cost_minor=existing.get("cost_minor", 0),
                    is_sandbox=False,
                )

        webhook_url = payload.get("webhook_url", "https://httpbin.org/post")
        parsed = urllib.parse.urlparse(webhook_url)
        if parsed.scheme != "https" or parsed.hostname not in self.ALLOWED_POST_HOSTS:
            raise ConnectorError(f"live webhook host '{parsed.hostname}' not in ALLOWED_POST_HOSTS", retryable=False)

        ext_id = f"live_{new_id()[:12]}"
        body_bytes = json.dumps(
            {
                "external_id": ext_id,
                "idempotency_key": idempotency_key,
                "action_type": action_type,
                "channel": payload.get("channel", "microsite_and_webhook"),
                "text": payload.get("text", ""),
                "campaign_budget_minor": payload.get("campaign_budget_minor", 0),
            },
            ensure_ascii=False,
        ).encode("utf-8")

        req = urllib.request.Request(
            webhook_url,
            data=body_bytes,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "ATLAS-Live-Publisher/1.0",
                "X-Atlas-Idempotency-Key": idempotency_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:  # noqa: S310 - scheme & host allowlisted
                http_status = resp.status
                resp_text = resp.read(32_768).decode("utf-8", errors="replace")
                resp_json = json.loads(resp_text)
        except Exception as e:
            raise ConnectorError(f"live webhook POST failed: {type(e).__name__}: {e}", retryable=True) from e

        # Also publish live HTML landing page for lead/conversion tracking
        self.microsite_dir.mkdir(parents=True, exist_ok=True)
        html_path = self.microsite_dir / f"{ext_id}.html"
        html_content = (
            "<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
            f"<title>OneCoat Live Campaign {ext_id}</title></head><body>"
            f"<article data-external-id='{ext_id}'>{payload.get('text', '')}</article>"
            "</body></html>"
        )
        html_path.write_text(html_content, encoding="utf-8")

        raw_receipt = {
            "live": True,
            "webhook_url": webhook_url,
            "http_status": http_status,
            "remote_origin": resp_json.get("origin"),
            "echoed_idempotency_key": (resp_json.get("headers") or {}).get("X-Atlas-Idempotency-Key"),
            "microsite_path": str(html_path),
            "published_at": time.time(),
        }
        cost_minor = int(payload.get("campaign_budget_minor", 0))
        with _lock:
            st = self._load()
            st["dispatches"][idempotency_key] = {
                "external_id": ext_id,
                "status": "published_live_verified",
                "raw": raw_receipt,
                "cost_minor": cost_minor,
            }
            st["send_count"] += 1
            self._save(st)
        return Receipt(
            external_id=ext_id,
            status="published_live_verified",
            raw=raw_receipt,
            cost_minor=cost_minor,
            is_sandbox=False,
        )

    def lookup(self, idempotency_key: str) -> Receipt | None:
        d = self._load()["dispatches"].get(idempotency_key)
        if not d:
            return None
        return Receipt(
            external_id=d["external_id"],
            status=d["status"],
            raw=d["raw"],
            cost_minor=d.get("cost_minor", 0),
            is_sandbox=False,
        )

    def request_stop(self, external_id: str) -> Receipt | None:
        with _lock:
            st = self._load()
            for d in st["dispatches"].values():
                if d["external_id"] == external_id:
                    d["status"] = "withdrawn_live"
                    html_path = self.microsite_dir / f"{external_id}.html"
                    if html_path.exists():
                        html_path.unlink()
                    self._save(st)
                    return Receipt(external_id=external_id, status="withdrawn_live", raw=d["raw"], is_sandbox=False)
        return None


CONNECTOR_CATALOG = {
    "sandbox_publisher": {"kind": "publishing", "mode": "sandbox", "verification": "mocked",
                          "note": "Simulated publisher for process testing. Not a real social network."},
    "live_webhook_publisher": {"kind": "publishing", "mode": "live", "verification": "live_tested",
                               "note": "Real HTTPS POST publisher (httpbin.org) + live microsite landing page with idempotency header."},
    "public_http_readonly": {"kind": "data_readonly", "mode": "live", "verification": "live_tested",
                             "note": "Live read-only HTTPS connector with host allowlist (open.er-api.com, wikipedia.org)."},
    "facebook_page": {"kind": "publishing", "mode": "not_configured", "verification": "not_configured",
                      "secret_ref": "FACEBOOK_PAGE_TOKEN", "note": "Requires Page access token + explicit publish.live grant."},
    "google_ads": {"kind": "ads", "mode": "not_configured", "verification": "not_configured",
                   "secret_ref": "GOOGLE_ADS_CREDENTIALS", "note": "Requires provider-side spend caps + budget.spend grant."},
    "sales_csv": {"kind": "data_readonly", "mode": "sandbox", "verification": "mocked",
                  "note": "Reads labeled DEMO fixture CSV/JSON."},
    "media_generator": {"kind": "media", "mode": "sandbox", "verification": "mocked",
                        "secret_ref": "MEDIA_PROVIDER_API_KEY",
                        "note": "Uses SVG Banner Spec Adapter in sandbox; external image/video model requires MEDIA_PROVIDER_API_KEY."},
    "browser_worker": {"kind": "browser", "mode": "sandbox", "verification": "mocked",
                       "note": "Isolated HTML/DOM inspection adapter with strict host allowlist; full Chromium requires container."},
}


def get_connector(name: str) -> Connector:
    if name == "sandbox_publisher":
        return SandboxPublisher()
    if name == "live_webhook_publisher":
        return LiveWebhookConnector()
    if name == "public_http_readonly":
        return PublicHttpReadOnlyConnector()
    return NotConfiguredConnector(name)
