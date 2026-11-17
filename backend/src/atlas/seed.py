"""Seed demo workspace/users/connectors. Demo tokens are for LOCAL DEMO ONLY (printed, not secrets of value)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.capabilities.registry import seed_capabilities
from atlas.integrations.connectors import CONNECTOR_CATALOG
from atlas.models import Connector, Policy, Role, User, Workspace
from atlas.policies.engine import DEFAULT_RULES
from atlas.security import hash_token

DEMO_USERS = [
    # (workspace, email, name, role, token)
    ("OneCoat Demo", "owner@demo.local", "Demo Owner", "owner", "demo-owner-token"),
    ("OneCoat Demo", "viewer@demo.local", "Demo Viewer", "viewer", "demo-viewer-token"),
    ("Other Workspace", "other@demo.local", "Other Tenant", "owner", "demo-other-token"),
]


def seed(s: Session) -> dict[str, str]:
    seed_capabilities(s)
    ws_ids: dict[str, str] = {}
    for ws_name, email, name, role, token in DEMO_USERS:
        ws = s.scalar(select(Workspace).where(Workspace.name == ws_name))
        if not ws:
            ws = Workspace(name=ws_name)
            s.add(ws)
            s.flush()
            s.add(Policy(workspace_id=ws.id, name="default", version=1, rules=DEFAULT_RULES))
            for cname, c in CONNECTOR_CATALOG.items():
                s.add(Connector(workspace_id=ws.id, name=cname, kind=c["kind"], mode=c["mode"], secret_ref=c.get("secret_ref"),
                                config={"note": c["note"]}, verification=c["verification"]))
        ws_ids[ws_name] = ws.id
        u = s.scalar(select(User).where(User.email == email))
        if not u:
            u = User(email=email, name=name, api_token_hash=hash_token(token))
            s.add(u)
            s.flush()
            s.add(Role(workspace_id=ws.id, user_id=u.id, role=role))
    s.flush()
    return ws_ids
