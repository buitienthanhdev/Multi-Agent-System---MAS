"""Seed initial demo missions and execute the OneCoat vertical slice so the database has rich initial state."""
from __future__ import annotations

from sqlalchemy import select

from atlas.actions import gateway
from atlas.db import create_all, session_scope
from atlas.execution import engine
from atlas.improvement import advance, propose_from_failures
from atlas.missions import service
from atlas.models import Action, Mission, Task, User
from atlas.seed import seed


def seed_diverse_missions() -> list[str]:
    """Ensure the workspace showcases diverse non-revenue missions (SOP/Runbook, Customer Care Playbook,
    Software Engineering Rate Limiter, Deep Research) alongside the revenue growth missions."""
    create_all()
    created_ids: list[str] = []
    with session_scope() as s:
        ws_map = seed(s)
        ws_id = ws_map["OneCoat Demo"]
        owner = s.scalar(select(User).where(User.email == "owner@demo.local"))
        existing_titles = {m.title for m in s.scalars(select(Mission).where(Mission.workspace_id == ws_id)).all()}

        diverse_prompts = [
            (
                "Xây dựng quy trình SOP ứng phó sự cố bảo mật & khôi phục dữ liệu (Disaster Recovery Runbook) cho hệ thống Cloud nội bộ.",
                True,
            ),
            (
                "Xây dựng kịch bản tư vấn kỹ thuật, xử lý khiếu nại và quy trình escalation cho đội ngũ chăm sóc khách hàng B2B.",
                True,
            ),
            (
                "Phát triển phần mềm viết module Token Bucket Rate Limiter bảo vệ API Gateway và chạy kiểm thử tự động trong sandbox.",
                True,
            ),
        ]
        for req_text, demo_flag in diverse_prompts:
            if req_text[:120] not in existing_titles:
                m = service.create_mission(s, ws_id, owner.id, req_text, is_demo=demo_flag)
                service.activate(s, m, owner.id)
                created_ids.append(m.id)

    for mid in created_ids:
        engine.run_until_idle("universal-seeder", mid)
    return created_ids
def populate_demo_state() -> dict:
    create_all()
    diverse_added = seed_diverse_missions()
    with session_scope() as s:
        ws_map = seed(s)
        ws_id = ws_map["OneCoat Demo"]
        owner = s.scalar(select(User).where(User.email == "owner@demo.local"))
        existing = s.scalars(select(Mission).where(Mission.workspace_id == ws_id)).all()
        if len(existing) > len(diverse_added):
            return {"status": "already_populated", "missions": len(existing), "diverse_added": len(diverse_added)}

        # 1. Completed OneCoat Mission (full 12-step vertical slice including revision loop & approval)
        m1 = service.create_mission(
            s,
            ws_id,
            owner.id,
            "Ngân sách tối đa 30 triệu đồng, hãy tìm cách đưa doanh thu sơn OneCoat lên 80 triệu đồng trong 30 ngày.",
            is_demo=True,
        )
        service.activate(s, m1, owner.id)
        ct = s.scalar(select(Task).where(Task.mission_id == m1.id, Task.key == "content"))
        ct.input = {"force_draft": "[DEMO] Sơn OneCoat bảo hành 10 năm, độ phủ 12m2/lít, cam kết 100% hài lòng!"}
        m1_id = m1.id

        # 2. Active OneCoat Mission paused at 'waiting_approval' so the user can click Approve on the Dashboard
        m2 = service.create_mission(
            s,
            ws_id,
            owner.id,
            "Ngân sách tối đa 15 triệu đồng, thử nghiệm bài đăng fanpage sơn OneCoat khu vực phía Nam trong 14 ngày.",
            is_demo=True,
        )
        service.activate(s, m2, owner.id)
        m2_id = m2.id

        # 3. Software Engineering Mission (OpenHands-style sandboxed patch proposal)
        m3 = service.create_mission(
            s,
            ws_id,
            owner.id,
            "Phát triển phần mềm viết công cụ kiểm tra UTM cho chiến dịch OneCoat trong 5 ngày.",
            is_demo=True,
        )
        service.activate(s, m3, owner.id)
        m3_id = m3.id

    # Run workers up to approval gates
    engine.run_until_idle("demo-seeder", m1_id)
    engine.run_until_idle("demo-seeder", m2_id)
    engine.run_until_idle("demo-seeder", m3_id)

    # Approve m1's publish action and run m1 to completion + generate improvement candidate
    with session_scope() as s:
        owner = s.scalar(select(User).where(User.email == "owner@demo.local"))
        act = s.scalar(select(Action).where(Action.mission_id == m1_id))
        gateway.decide(s, act, owner.id, "approved", act.payload_hash, "Duyệt đăng thử nghiệm trên sandbox")
        engine.on_action_decided(s, act)
    engine.run_until_idle("demo-seeder", m1_id)

    with session_scope() as s:
        cand = propose_from_failures(s)
        if cand:
            advance(s, cand)
            advance(s, cand)

    return {"status": "populated", "completed_mission": m1_id, "awaiting_approval_mission": m2_id, "software_mission": m3_id}


if __name__ == "__main__":
    print(populate_demo_state())
