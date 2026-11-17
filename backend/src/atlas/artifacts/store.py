"""Artifact storage. Local filesystem adapter with an S3-compatible-shaped interface (put/get by key) and
HMAC-signed, expiring download URLs. Swap for an S3/MinIO adapter in production."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from pathlib import Path

from sqlalchemy.orm import Session

from atlas.config import get_settings
from atlas.models import Artifact, ArtifactVersion

_SIGNING_KEY = os.getenv("ATLAS_URL_SIGNING_KEY", "dev-only-signing-key").encode()


class LocalObjectStore:
    def __init__(self, root: Path | None = None):
        self.root = root or get_settings().object_store_dir

    def put(self, key: str, data: bytes) -> str:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(data)
        return f"local://{key}"

    def get(self, uri: str) -> bytes:
        key = uri.removeprefix("local://")
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise PermissionError("path traversal")
        return p.read_bytes()


def sign_url(version_id: str, ttl: int = 300) -> str:
    exp = int(time.time()) + ttl
    sig = hmac.new(_SIGNING_KEY, f"{version_id}:{exp}".encode(), hashlib.sha256).hexdigest()
    return f"/api/files/{version_id}?exp={exp}&sig={sig}"


def verify_signature(version_id: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    good = hmac.new(_SIGNING_KEY, f"{version_id}:{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, sig)


def save_artifact(s: Session, *, workspace_id: str, mission_id: str, task_id: str | None, kind: str, title: str,
                  content: str, is_demo: bool) -> ArtifactVersion:
    data = content.encode("utf-8")
    h = hashlib.sha256(data).hexdigest()
    uri = LocalObjectStore().put(f"{workspace_id}/{h}.txt", data)
    art = s.query(Artifact).filter_by(mission_id=mission_id, task_id=task_id, kind=kind).one_or_none()
    if art is None:
        art = Artifact(workspace_id=workspace_id, mission_id=mission_id, task_id=task_id, kind=kind, title=title,
                       current_version=0, is_demo=is_demo)
        s.add(art)
        s.flush()
    last = s.query(ArtifactVersion).filter_by(artifact_id=art.id, version=art.current_version).one_or_none()
    if last is not None and last.content_hash == h:
        return last
    art.current_version += 1
    v = ArtifactVersion(artifact_id=art.id, version=art.current_version, content_hash=h, storage_uri=uri,
                        content_preview=content[:4000], meta={"is_demo": is_demo})
    s.add(v)
    s.flush()
    return v
