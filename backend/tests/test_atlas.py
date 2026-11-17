"""Verification & acceptance test suite covering all 15 required invariants + Vertical Slice E2E + Benchmark."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from atlas.actions import gateway
from atlas.agents.base import AgentContext, AgentLimits, LimitExceeded, ToolBox, ToolPermissionDenied
from atlas.agents.specialists import AGENTS, fixture_tools
from atlas.api import app
from atlas.budgets import ledger
from atlas.budgets.ledger import BudgetExceeded
from atlas.config import get_settings
from atlas.db import SessionLocal, create_all, reset_engine, session_scope, utcnow
from atlas.evaluations.evaluator import evaluate_content, evaluate_report_numbers
from atlas.execution import engine
from atlas.improvement import advance, propose_from_failures
from atlas.integrations.connectors import SandboxPublisher
from atlas.llm import DeepAgentsProvider, LLMResult, set_provider
from atlas.missions import service
from atlas.missions.compiler import compile_mission
from atlas.models import (Action, Approval, BudgetAccount, Evaluation, Evidence, ImprovementCandidate, Mission,
                          Report, Task, User)
from atlas.reporting.reports import build_report_content, create_report
from atlas.seed import seed


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "test_atlas.db"
    obj_dir = tmp_path / "objects"
    sbx_file = tmp_path / "sandbox.json"
    monkeypatch.setenv("ATLAS_DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("ATLAS_OBJECT_STORE_DIR", str(obj_dir))
    monkeypatch.setenv("ATLAS_SANDBOX_STATE_FILE", str(sbx_file))
    monkeypatch.setenv("ATLAS_LEASE_SECONDS", "2")
    monkeypatch.setenv("ATLAS_LLM_MODEL", "template")
    monkeypatch.delenv("ATLAS_SANDBOX_FAULT", raising=False)
    reset_engine()
    create_all()
    with session_scope() as s:
        ws = seed(s)
    yield {"db_file": db_file, "obj_dir": obj_dir, "sbx_file": sbx_file, "ws": ws}
    set_provider(None)
    reset_engine()


def _owner_and_ws():
    with session_scope() as s:
        u = s.scalar(select(User).where(User.email == "owner@demo.local"))
        ws_id = seed(s)["OneCoat Demo"]
        return u.id, ws_id


# 1. Two workers concurrently reserving budget cannot exceed limit
def test_01_concurrent_budget_reservations_do_not_exceed_limit():
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách tối đa 30 triệu đồng, đưa doanh thu sơn OneCoat lên 80 triệu trong 30 ngày.")
        service.activate(s, m, uid)
        acc = s.scalar(select(BudgetAccount).where(BudgetAccount.mission_id == m.id, BudgetAccount.category == "total"))
        acc_id = acc.id

    results: dict[int, str] = {}
    barrier = threading.Barrier(2)

    def worker_reserve(idx: int):
        s = SessionLocal()
        try:
            barrier.wait(timeout=5)
            ledger.reserve(s, acc_id, 20_000_000, f"concurrent-key-{idx}")
            s.commit()
            results[idx] = "ok"
        except BudgetExceeded:
            s.rollback()
            results[idx] = "exceeded"
        finally:
            s.close()

    t1 = threading.Thread(target=worker_reserve, args=(1,))
    t2 = threading.Thread(target=worker_reserve, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(results.values()) == ["exceeded", "ok"]
    winner = next(idx for idx, status in results.items() if status == "ok")
    with session_scope() as s:
        acc = s.get(BudgetAccount, acc_id)
        assert acc.reserved_minor == 20_000_000
        assert acc.reserved_minor <= acc.limit_minor
        # Idempotent retry with the winning key does not double-reserve
        ledger.reserve(s, acc_id, 20_000_000, f"concurrent-key-{winner}")
        s.flush()
        s.refresh(acc)
        assert acc.reserved_minor == 20_000_000


# 2. Retry does not create duplicate external actions when connector supports idempotency
def test_02_retry_idempotency_no_duplicate_external_action():
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách tối đa 30 triệu đồng, đưa doanh thu sơn OneCoat lên 80 triệu trong 30 ngày.")
        service.activate(s, m, uid)
        a = gateway.prepare_action(s, m, None, "sandbox_publisher", "publish.sandbox", {"text": "[DEMO] OneCoat test"}, 0, uid)
        gateway.decide(s, a, uid, "approved", a.payload_hash)
        s.commit()
        gateway.execute(s, a.id, "w1")
        gateway.execute(s, a.id, "w2")  # second execute call

    sbx = SandboxPublisher()
    assert sbx.send_count() == 1


# 3. Unknown outcome on timeout transitions to reconciliation and recovers without duplicate send
def test_03_timeout_triggers_reconciliation(monkeypatch: pytest.MonkeyPatch):
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách tối đa 30 triệu đồng, đưa doanh thu sơn OneCoat lên 80 triệu trong 30 ngày.")
        service.activate(s, m, uid)
        a = gateway.prepare_action(s, m, None, "sandbox_publisher", "publish.sandbox", {"text": "[DEMO] OneCoat timeout"}, 0, uid)
        gateway.decide(s, a, uid, "approved", a.payload_hash)
        s.commit()
        aid = a.id

    monkeypatch.setenv("ATLAS_SANDBOX_FAULT", "timeout_after_send")
    with session_scope() as s:
        a = gateway.execute(s, aid, "w1")
        assert a.status == "succeeded"  # reconciled from remote state
        assert a.external_ref is not None
    assert SandboxPublisher().send_count() == 1


# 4. Crash after external success but before local persistence is recovered on restart via reconciliation
def test_04_crash_after_external_send_recovered_without_duplicate(isolated_env):
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách tối đa 30 triệu đồng, đưa doanh thu sơn OneCoat lên 80 triệu trong 30 ngày.")
        service.activate(s, m, uid)
        a = gateway.prepare_action(s, m, None, "sandbox_publisher", "publish.sandbox", {"text": "[DEMO] OneCoat crash"}, 0, uid)
        gateway.decide(s, a, uid, "approved", a.payload_hash)
        s.commit()
        aid = a.id

    # Run a child process that crashes (os._exit(17)) right after sandbox_publisher writes remote state
    env = os.environ.copy()
    env["ATLAS_SANDBOX_FAULT"] = "crash_after_send"
    code = (
        "from atlas.db import SessionLocal; from atlas.actions import gateway; "
        f"s=SessionLocal(); gateway.execute(s, {aid!r}, 'crash-worker')"
    )
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert proc.returncode == 17
    assert SandboxPublisher().send_count() == 1

    # Local DB still shows 'executing' because child died before _record_success
    with session_scope() as s:
        a = s.get(Action, aid)
        assert a.status == "executing"
        # Recovery worker runs execute() -> reconciles first -> marks succeeded without a second send
        a = gateway.execute(s, aid, "recovery-worker")
        assert a.status == "succeeded"
        assert a.external_ref is not None
    assert SandboxPublisher().send_count() == 1


# 5. Expired approval or modified payload is rejected
def test_05_expired_approval_and_payload_mutation_rejected():
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách tối đa 30 triệu đồng, đưa doanh thu sơn OneCoat lên 80 triệu trong 30 ngày.")
        service.activate(s, m, uid)
        a = gateway.prepare_action(s, m, None, "sandbox_publisher", "publish.sandbox", {"text": "[DEMO] v1"}, 0, uid)
        # Wrong hash when approving -> rejected
        with pytest.raises(gateway.ApprovalInvalid):
            gateway.decide(s, a, uid, "approved", "wrong_hash")
        ap = gateway.decide(s, a, uid, "approved", a.payload_hash)
        s.commit()
        # Mutating payload invalidates existing approval
        gateway.update_payload(s, a, {"text": "[DEMO] v2 tampered"}, uid)
        s.commit()
        with pytest.raises(gateway.ApprovalInvalid):
            gateway.execute(s, a.id, "w1")
        # Approve v2, then expire the approval -> rejected at execute time
        ap2 = gateway.decide(s, a, uid, "approved", a.payload_hash)
        ap2.expires_at = utcnow() - timedelta(minutes=1)
        s.commit()
        with pytest.raises(gateway.ApprovalInvalid):
            gateway.execute(s, a.id, "w1")


# 6. Cross-workspace isolation: user cannot read or modify another workspace's Mission
def test_06_workspace_isolation_via_api():
    client = TestClient(app)
    owner_hdr = {"Authorization": "Bearer demo-owner-token"}
    other_hdr = {"Authorization": "Bearer demo-other-token"}
    viewer_hdr = {"Authorization": "Bearer demo-viewer-token"}

    me = client.get("/api/me", headers=owner_hdr).json()
    ws_id = me["workspaces"][0]["id"]
    created = client.post("/api/missions", headers=owner_hdr,
                          json={"workspace_id": ws_id, "request": "Ngân sách 30 triệu, doanh thu OneCoat 80 triệu trong 30 ngày"}).json()
    mid = created["id"]

    # Other workspace user gets 404 on read and write
    assert client.get(f"/api/missions/{mid}", headers=other_hdr).status_code == 404
    assert client.post(f"/api/missions/{mid}/activate", headers=other_hdr).status_code == 404
    assert client.get("/api/missions", params={"workspace_id": ws_id}, headers=other_hdr).status_code == 404
    # Viewer in same workspace can read, cannot write
    assert client.get(f"/api/missions/{mid}", headers=viewer_hdr).status_code == 200
    assert client.post(f"/api/missions/{mid}/activate", headers=viewer_hdr).status_code == 403


# 7. Agent cannot call tools outside its capability permission set
def test_07_agent_cannot_call_unpermitted_tool():
    tb = ToolBox(allowed={"fixture_web.list"}, registry=fixture_tools(), limits=AgentLimits())
    assert tb.call("fixture_web.list")
    with pytest.raises(ToolPermissionDenied):
        tb.call("sales_fixture.read")
    assert "sales_fixture.read" in tb.denied


# 8. Untrusted malicious web content does not escalate permissions, approve actions, or leak secrets
def test_08_prompt_injection_in_external_source_is_contained(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ATLAS_DEMO_SECRET", "TOP_SECRET_VALUE_999")
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách tối đa 30 triệu đồng, đưa doanh thu sơn OneCoat lên 80 triệu trong 30 ngày.")
        before_actions = list(service.current_contract(s, m)["permitted_actions"])
        service.activate(s, m, uid)
        mid = m.id

    engine.run_until_idle("w-sec", mid)
    with session_scope() as s:
        m = s.get(Mission, mid)
        after_actions = service.current_contract(s, m)["permitted_actions"]
        assert after_actions == before_actions  # permissions unchanged
        assert "budget.spend" not in after_actions
        evs = s.scalars(select(Evidence).where(Evidence.mission_id == mid)).all()
        flagged = [e for e in evs if e.untrusted_flags]
        assert flagged, "Malicious fixture source must be flagged"
        for e in evs:
            assert "TOP_SECRET_VALUE_999" not in e.claim
        # Publish action is still waiting for human approval, not auto-approved
        acts = s.scalars(select(Action).where(Action.mission_id == mid)).all()
        assert all(a.status == "awaiting_approval" for a in acts)


# 9. Worker killed mid-run: another worker resumes after lease expiry without losing committed progress
def test_09_worker_crash_and_resume_preserves_progress():
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách tối đa 30 triệu đồng, đưa doanh thu sơn OneCoat lên 80 triệu trong 30 ngày.")
        service.activate(s, m, uid)
        mid = m.id

    # Worker 1 completes research + baseline, then claims 'content' and dies before finishing
    with session_scope() as s:
        tid1 = engine.claim_next(s, "w1", mid)
    engine.run_task(tid1, "w1")
    with session_scope() as s:
        tid2 = engine.claim_next(s, "w1", mid)
    engine.run_task(tid2, "w1")
    with session_scope() as s:
        tid_stuck = engine.claim_next(s, "w1-crashed", mid)
        t = s.get(Task, tid_stuck)
        assert t.status == "running" and t.lease_owner == "w1-crashed"
        # Simulate lease expiry after w1-crashed died
        t.lease_until = utcnow() - timedelta(seconds=1)
        s.commit()

    # Worker 2 takes over expired lease and runs until waiting_approval on publish
    engine.run_until_idle("w2-recovery", mid)
    with session_scope() as s:
        tasks = {t.key: t.status for t in s.scalars(select(Task).where(Task.mission_id == mid))}
        assert tasks["research"] == "completed"
        assert tasks["baseline"] == "completed"
        assert tasks["content"] == "completed"
        assert tasks["review"] == "completed"
        assert tasks["publish"] == "waiting_approval"


# 10. Pause and Cancel block new actions; cancel requests stop on already-published sandbox items
def test_10_pause_and_cancel_block_actions():
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách tối đa 30 triệu đồng, đưa doanh thu sơn OneCoat lên 80 triệu trong 30 ngày.")
        service.activate(s, m, uid)
        a = gateway.prepare_action(s, m, None, "sandbox_publisher", "publish.sandbox", {"text": "[DEMO] OneCoat"}, 0, uid)
        gateway.decide(s, a, uid, "approved", a.payload_hash)
        service.pause(s, m, uid)
        s.commit()
        with pytest.raises(gateway.PolicyDenied):
            gateway.execute(s, a.id, "w1")
        service.resume(s, m, uid)
        s.commit()
        gateway.execute(s, a.id, "w1")
        res = service.cancel(s, m, uid)
        s.commit()
        assert res["external_stops"] == [{"action_id": a.id, "stop": "verified"}]
        a2 = gateway.prepare_action(s, m, None, "sandbox_publisher", "publish.sandbox", {"text": "[DEMO] after cancel"}, 0, uid)
        assert a2.status == "rejected"


# 11. Agent loop exceeding resource limits is stopped deterministically
def test_11_agent_resource_limits_enforced():
    tb = ToolBox(allowed={"fixture_web.list"}, registry=fixture_tools(), limits=AgentLimits(max_tool_calls=2, max_tokens=100))
    tb.call("fixture_web.list")
    tb.call("fixture_web.list")
    with pytest.raises(LimitExceeded):
        tb.call("fixture_web.list")

    tb2 = ToolBox(allowed=set(), registry={}, limits=AgentLimits(max_tokens=50))
    with pytest.raises(LimitExceeded):
        tb2.add_tokens(51)


# 12. Provider failure is handled via retry and fallback policy without breaking the task
def test_12_provider_error_retry_and_fallback():
    class BrokenModel:
        _is_mock_broken = True

        def invoke(self, *a, **k):
            raise RuntimeError("503 model overloaded")

    p = DeepAgentsProvider(BrokenModel(), max_retries=1)
    r = p.generate("sys", "user prompt", "[DEMO] OneCoat fallback content")
    assert "fallback:template" in r.provider
    assert r.text == "[DEMO] OneCoat fallback content"
    assert any("fell back to template" in x for x in r.limitations)


# 13. Reports never include unverified estimates inside verified_results
def test_13_report_separates_verified_from_estimates():
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách tối đa 30 triệu đồng, đưa doanh thu sơn OneCoat lên 80 triệu trong 30 ngày.")
        service.activate(s, m, uid)
        mid = m.id
    engine.run_until_idle("w1", mid)
    with session_scope() as s:
        a = s.scalar(select(Action).where(Action.mission_id == mid))
        gateway.decide(s, a, uid, "approved", a.payload_hash)
        engine.on_action_decided(s, a)
        s.commit()
    engine.run_until_idle("w1", mid)
    with session_scope() as s:
        rep = s.scalar(select(Report).where(Report.mission_id == mid))
        assert rep is not None
        assert evaluate_report_numbers(rep.content) == []
        assert rep.content["verified_results"]
        assert rep.content["estimates_not_verified"]
        assert rep.delivery_status == "not_sent_channel_not_configured"


# 14. Full vertical slice E2E via HTTP API (dashboard backend contract) + review revision loop + improvement pipeline
def test_14_vertical_slice_e2e_and_revision_and_improvement():
    client = TestClient(app)
    hdr = {"Authorization": "Bearer demo-owner-token"}
    ws_id = client.get("/api/me", headers=hdr).json()["workspaces"][0]["id"]

    # Create + activate OneCoat mission
    m = client.post("/api/missions", headers=hdr, json={
        "workspace_id": ws_id,
        "request": "Ngân sách tối đa 30 triệu đồng, hãy tìm cách đưa doanh thu sơn OneCoat lên 80 triệu đồng trong 30 ngày."
    }).json()
    mid = m["id"]
    assert m["contract"]["budget"]["amount_minor"] == 30_000_000
    assert m["contract"]["target"]["amount_minor"] == 80_000_000
    assert "budget.spend" not in m["contract"]["permitted_actions"]
    assert m["contract"]["unresolved_questions"]

    client.post(f"/api/missions/{mid}/activate", headers=hdr)
    # Inject a bad first draft (contains forbidden warranty claim) to verify Reviewer rejection -> revision loop
    with session_scope() as s:
        ct = s.scalar(select(Task).where(Task.mission_id == mid, Task.key == "content"))
        ct.input = {"force_draft": "[DEMO] Sơn OneCoat bảo hành 10 năm, độ phủ 12m2/lít, cam kết 100% hài lòng!"}
        s.commit()

    engine.run_until_idle("w-e2e", mid)

    # Reviewer rejected v1, content revised to v2 without force_draft, Reviewer accepted v2, now publish awaits approval
    evals = client.get(f"/api/missions/{mid}/evaluations", headers=hdr).json()
    assert [e["verdict"] for e in evals] == ["revision_requested", "accepted"]

    acts = client.get(f"/api/missions/{mid}/actions", headers=hdr).json()
    assert len(acts) == 1 and acts[0]["status"] == "awaiting_approval"

    # Approve with exact payload_hash
    dec = client.post(f"/api/actions/{acts[0]['id']}/decide", headers=hdr,
                      json={"decision": "approved", "payload_hash": acts[0]["payload_hash"], "comment": "OK sandbox"})
    assert dec.status_code == 200

    # Resume worker to finish publish -> analytics results -> final report -> mission completed
    engine.run_until_idle("w-e2e", mid)

    detail = client.get(f"/api/missions/{mid}", headers=hdr).json()
    assert detail["status"] == "completed"
    plan_data = client.get(f"/api/missions/{mid}/plan", headers=hdr).json()
    assert all(t["status"] == "completed" for t in plan_data["tasks"])
    arts = client.get(f"/api/missions/{mid}/artifacts", headers=hdr).json()
    assert {a["kind"] for a in arts} >= {"research_brief", "post_draft", "report"}
    # Signed URL works and rejects tampering
    dl_url = arts[0]["versions"][-1]["download_url"]
    assert client.get(dl_url).status_code == 200
    assert client.get(dl_url + "x").status_code == 403

    # Controlled improvement pipeline from recorded review failure
    with session_scope() as s:
        cand = propose_from_failures(s)
        assert cand is not None and cand.status == "candidate"
        advance(s, cand)
        assert cand.status == "sandbox_passed"
        advance(s, cand)
        assert cand.status == "heldout_passed"
        advance(s, cand)
        assert cand.status == "limited_rollout"
        advance(s, cand, {"acceptance_rate": 0.95, "baseline_acceptance_rate": 0.80})
        assert cand.status == "promoted"
        # Forbidden target (policy/budget) is rejected
        bad = ImprovementCandidate(target_type="policy", target_name="default_policy", description="x", proposal={})
        s.add(bad)
        s.flush()
        advance(s, bad)
        assert bad.status == "rejected_forbidden_target"


# 15. Backup and restore verification in isolated test environment
def test_15_backup_and_restore_roundtrip(isolated_env, tmp_path: Path):
    from atlas.ops import backup_state, restore_state
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách 30 triệu, doanh thu OneCoat 80 triệu trong 30 ngày.")
        service.activate(s, m, uid)
        mid = m.id
    engine.run_until_idle("w-bak", mid)

    archive = tmp_path / "backup.tar.gz"
    backup_state(archive)
    assert archive.exists()

    # Wipe DB + objects, then restore and verify mission & artifacts are intact
    reset_engine()
    isolated_env["db_file"].unlink()
    restore_state(archive)
    with session_scope() as s:
        m = s.get(Mission, mid)
        assert m is not None and m.status == "active"
        tasks = s.scalars(select(Task).where(Task.mission_id == mid)).all()
        assert any(t.status == "waiting_approval" for t in tasks)


# 16. Benchmark comparison: Multi-agent (with independent review loop) vs Single-pass (no review gate)
def test_16_multi_agent_vs_single_agent_benchmark():
    from atlas.benchmark import run_benchmark
    res = run_benchmark()
    assert res["multi_agent"]["policy_violation_escape_rate"] == 0.0
    assert res["single_agent"]["policy_violation_escape_rate"] > 0.0
    assert res["multi_agent"]["tasks_evaluated"] == res["single_agent"]["tasks_evaluated"]


# 17. All 6 domain task types (market_research, content_media, customer_care, software, data_analysis, docs_ops) run E2E
def test_17_all_six_additional_domain_task_types_run_e2e():
    uid, ws_id = _owner_and_ws()
    prompts = [
        ("market_research", "Nghiên cứu thị trường sơn trang trí nội thất cuối năm trong 14 ngày."),
        ("content_media", "Tạo nội dung và media banner giới thiệu dòng sơn OneCoat trong 7 ngày."),
        ("customer_care", "Xây dựng kịch bản tư vấn và chăm sóc khách hàng hỏi giá sơn OneCoat trong 10 ngày."),
        ("software", "Phát triển phần mềm viết công cụ kiểm tra UTM cho chiến dịch OneCoat trong 5 ngày."),
        ("data_analysis", "Phân tích dữ liệu bán hàng và đối chứng hiệu quả chiến dịch trong 15 ngày."),
        ("docs_ops", "Soạn tài liệu quy trình vận hành nội bộ cho đội dự án trong 7 ngày."),
    ]
    for expected_type, text in prompts:
        with session_scope() as s:
            m = service.create_mission(s, ws_id, uid, text)
            assert m.task_type == expected_type
            service.activate(s, m, uid)
            mid = m.id
        engine.run_until_idle(f"w-{expected_type}", mid)
        with session_scope() as s:
            m = s.get(Mission, mid)
            assert m.status == "completed", f"{expected_type} did not complete: {m.status}"


# 18. Live read-only HTTP connector enforces host allowlist and fetches real public reference data
def test_18_public_http_readonly_connector_allowlist_and_live_fetch():
    from atlas.integrations.connectors import ConnectorError, PublicHttpReadOnlyConnector
    conn = PublicHttpReadOnlyConnector()
    # Disallowed host or scheme is blocked immediately (SSRF / egress protection)
    with pytest.raises(ConnectorError):
        conn.fetch_json_or_text("http://127.0.0.1:8000/api/health")
    with pytest.raises(ConnectorError):
        conn.fetch_json_or_text("https://evil.example.com/data.json")
    # Live HTTPS fetch against allowlisted public exchange-rate reference endpoint
    res = conn.fetch_json_or_text("https://open.er-api.com/v6/latest/USD")
    assert res["status"] == "fetched_live"
    assert res["json"]["result"] == "success"
    assert "VND" in res["json"]["rates"]


# 19. Statistical DiD, Parallel Trends Test, Full Funnel KPIs, and Closed-Loop Optimization (Steps 5 & 6)
def test_19_statistical_did_parallel_trends_and_closed_loop_optimization():
    from atlas.analytics_engine import analyze_business_kpis, closed_loop_replan
    from atlas.live_pilot import _seed_live_kpi_ledger
    uid, ws_id = _owner_and_ws()
    with session_scope() as s:
        m = service.create_mission(s, ws_id, uid, "Ngân sách 10 triệu, tăng doanh thu sơn OneCoat trong 14 ngày.", is_demo=False)
        service.activate(s, m, uid)
        _seed_live_kpi_ledger(s, ws_id, m.id)
        s.flush()
        from atlas.models import BusinessKPIEvent
        events = s.scalars(select(BusinessKPIEvent).where(BusinessKPIEvent.mission_id == m.id)).all()
        summary = analyze_business_kpis(list(events))
        assert summary["did_inference"]["parallel_trends_passed"] is True
        assert summary["did_inference"]["parallel_trends_pvalue"] >= 0.05
        assert summary["did_inference"]["statistically_significant_95"] is True
        assert summary["did_inference"]["p_value"] < 0.05
        assert summary["roi"]["incremental_roas"] > 1.0
        assert summary["funnel"]["qualified_leads"] > 0
        cl = closed_loop_replan(s, m, summary)
        assert cl["action_code"] == "propose_scale_winning_channel"
        assert cl["best_channel"] == "technical_consultation_microsite"


# 20. Live Webhook Publisher Connector: real HTTPS POST + idempotency + microsite generation + withdrawal (Step 4)
def test_20_live_webhook_publisher_idempotency_and_withdrawal():
    from atlas.integrations.connectors import LiveWebhookConnector
    conn = LiveWebhookConnector()
    r1 = conn.execute(
        "publish.live",
        {"channel": "microsite", "webhook_url": "https://httpbin.org/post", "text": "OneCoat live test", "campaign_budget_minor": 1_500_000},
        idempotency_key="live-idem-key-001",
    )
    assert r1.is_sandbox is False
    assert r1.status == "published_live_verified"
    assert r1.raw["http_status"] == 200
    assert r1.raw["echoed_idempotency_key"] == "live-idem-key-001"
    # Second call with same idempotency_key returns existing receipt without second HTTP POST
    r2 = conn.execute(
        "publish.live",
        {"channel": "microsite", "webhook_url": "https://httpbin.org/post", "text": "OneCoat live test", "campaign_budget_minor": 1_500_000},
        idempotency_key="live-idem-key-001",
    )
    assert r2.external_id == r1.external_id
    stopped = conn.request_stop(r1.external_id)
    assert stopped is not None and stopped.status == "withdrawn_live"


# 21. Reviewer's Special Live Acceptance Challenge: Real LLM (gemma4:12b) + Real HTTPS Research + Live Webhook Publisher + KPI Pipeline
def test_21_special_live_acceptance_pilot_no_demo_no_template_no_sandbox():
    from atlas.live_pilot import run_live_acceptance_pilot
    res = run_live_acceptance_pilot()
    assert res["mission_status"] == "completed"
    assert res["is_demo"] is False
    # Verify real LLM (deepagents(ollama:gemma4:12b)) ran on research, content, and review
    providers = [list(x.values())[0] for x in res["agent_providers_used"]]
    assert any("ollama:gemma4:12b" in p for p in providers)
    assert not any(p == "template(no-llm)" for p in providers)
    # Verify real HTTPS sources and KPI ledger were cited as verified_fact, and NO demo fixture was used
    assert "https://vi.wikipedia.org/api/rest_v1/page/summary/S%C6%A1n" in res["live_sources_verified"]
    assert "https://open.er-api.com/v6/latest/USD" in res["live_sources_verified"]
    assert not any("fixture://" in src for src in res["live_sources_verified"])
    # Verify live webhook publisher (not sandbox_publisher) executed and settled budget
    assert res["action_executed"]["connector"] == "live_webhook_publisher"
    assert res["action_executed"]["is_sandbox_receipt"] is False
    assert res["action_executed"]["webhook_http_status"] == 200
    assert res["budget_settled"]["ads"]["settled"] == 3_500_000
    # Verify closed-loop optimization decision was recorded
    assert any(d["kind"] == "closed_loop_optimization" for d in res["closed_loop_decisions"])


