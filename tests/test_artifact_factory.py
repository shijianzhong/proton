import pathlib
import sys
import asyncio

from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.api.main import create_app
from src.artifacts import service as artifact_module
from src.copilot import service as copilot_module
from src.orchestration import workflow as workflow_module
from src.plugins import skill_manager as skill_manager_module
from src.storage import persistence as persistence_module


def _reset_singletons():
    persistence_module._storage_manager = None
    artifact_module._artifact_factory_service = None
    workflow_module._global_manager = None
    skill_manager_module._skill_manager = None
    copilot_module._global_copilot = None


def test_artifact_factory_generates_skill_candidate_and_materializes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())

    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u1",
            "task_summary": "把日报结构化并输出固定格式",
            "repeat_count": 3,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "parallel_branches": 0,
            "requires_long_running": False,
            "has_manual_steps": False,
            "failure_rate": 0.05,
            "high_risk": False,
        },
    )
    assert decide_resp.status_code == 200
    candidate = decide_resp.json()
    assert candidate["artifact_type"] == "skill"

    approve_resp = client.post(
        f"/api/artifacts/candidates/{candidate['id']}/approve",
        json={"approver": "qa", "bind_agent_id": "agent-a"},
    )
    assert approve_resp.status_code == 200
    materialized = approve_resp.json()
    assert materialized["status"] == "materialized"
    assert materialized["materialized_ref_id"]

    list_resp = client.get("/api/artifacts/candidates", params={"user_id": "u1"})
    assert list_resp.status_code == 200
    candidates = list_resp.json()
    assert any(item["id"] == candidate["id"] for item in candidates)


def test_artifact_factory_generates_workflow_candidate_and_materializes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())

    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u2",
            "task_summary": "多渠道内容生产并并行校审",
            "repeat_count": 1,
            "tool_call_count": 6,
            "unique_tool_count": 4,
            "parallel_branches": 3,
            "requires_long_running": True,
            "has_manual_steps": True,
            "failure_rate": 0.1,
            "high_risk": False,
        },
    )
    assert decide_resp.status_code == 200
    candidate = decide_resp.json()
    assert candidate["artifact_type"] == "workflow"

    approve_resp = client.post(
        f"/api/artifacts/candidates/{candidate['id']}/approve",
        json={"approver": "ops"},
    )
    assert approve_resp.status_code == 200
    materialized = approve_resp.json()
    assert materialized["status"] == "materialized"
    workflow_id = materialized["materialized_ref_id"]
    assert workflow_id

    wf_resp = client.get(f"/api/workflows/{workflow_id}")
    assert wf_resp.status_code == 200


def test_artifact_factory_decide_from_real_trajectory(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    session_resp = client.post("/api/copilot/sessions", json={})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["session_id"]

    copilot = copilot_module.get_copilot_service()
    asyncio.run(
        copilot.session_manager.add_message(
            session_id=session_id,
            role="user",
            content="请帮我做长期运行的舆情监控并加入人工审批",
        )
    )
    asyncio.run(
        copilot.session_manager.add_message(
            session_id=session_id,
            role="user",
            content="请帮我做长期运行的舆情监控并加入人工审批",
        )
    )
    asyncio.run(
        copilot.session_manager.add_message(
            session_id=session_id,
            role="assistant",
            content="我会先创建流程，再补充查询结构。",
            tool_calls=[
                {"id": "tc-1", "name": "generate_workflow", "arguments": "{}"},
                {"id": "tc-2", "name": "get_workflow_summary", "arguments": "{}"},
            ],
        )
    )

    decide_resp = client.post(
        "/api/artifacts/decide/from-trajectory",
        json={"user_id": "u-trace", "session_id": session_id, "metadata": {"source": "test"}},
    )
    assert decide_resp.status_code == 200
    candidate = decide_resp.json()
    assert candidate["source_session_id"] == session_id
    assert candidate["artifact_type"] == "workflow"
    assert candidate["metadata"]["signal_source"] == "execution_trajectory"
    assert candidate["metadata"]["trajectory"]["tool_call_count"] == 2


def test_artifact_factory_decide_from_real_trajectory_session_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide/from-trajectory",
        json={"user_id": "u-trace", "session_id": "not-exist"},
    )
    assert decide_resp.status_code == 404


def test_artifact_factory_merges_audit_and_approval_signals(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    session_resp = client.post("/api/copilot/sessions", json={})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["session_id"]

    copilot = copilot_module.get_copilot_service()
    asyncio.run(
        copilot.session_manager.add_message(
            session_id=session_id,
            role="user",
            content="请帮我搭一个自动化脚本",
        )
    )
    asyncio.run(
        copilot.session_manager.add_message(
            session_id=session_id,
            role="assistant",
            content="需要审批后执行",
            tool_calls=[{"id": "tc-audit-1", "name": "shell_exec", "arguments": "{}"}],
            tool_results=[
                {
                    "tool_call_id": "tc-audit-1",
                    "status": "error",
                    "metadata": {"approval_status": "pending", "approval_id": "ap-msg-1"},
                }
            ],
        )
    )

    decide_resp = client.post(
        "/api/artifacts/decide/from-trajectory",
        json={
            "user_id": "u-merge",
            "session_id": session_id,
            "tool_execution_audit": [
                {
                    "tool_call_id": "tc-audit-2",
                    "tool_name": "shell_exec",
                    "status": "denied",
                    "is_dangerous": True,
                    "is_error": True,
                }
            ],
            "approval_results": [{"status": "approved", "approval_id": "ap-manual-1"}],
        },
    )
    assert decide_resp.status_code == 200
    candidate = decide_resp.json()
    assert candidate["metadata"]["trajectory"]["audit_entry_count"] == 1
    assert candidate["metadata"]["trajectory"]["approval_signal_count"] >= 2
    assert candidate["artifact_type"] == "none"
    assert candidate["reasons"][0].startswith("高风险")


def test_artifact_factory_collect_effect_metrics_and_auto_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-metrics",
            "task_summary": "结构化客服问答",
            "repeat_count": 3,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.02,
        },
    )
    assert decide_resp.status_code == 200
    candidate_id = decide_resp.json()["id"]

    approve_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/approve",
        json={"approver": "qa"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["rollout_status"] == "not_started"

    transition_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={"target_status": "grayscale", "operator": "release-bot", "reason": "start canary"},
    )
    assert transition_resp.status_code == 200
    assert transition_resp.json()["rollout_status"] == "grayscale"

    for _ in range(20):
        metric_resp = client.post(
            f"/api/artifacts/candidates/{candidate_id}/metrics",
            json={
                "reporter": "abtest",
                "metrics": {
                    "success_rate": 0.99,
                    "error_rate": 0.01,
                    "latency_p95_ms": 1800,
                    "quality_score": 0.96,
                },
            },
        )
        assert metric_resp.status_code == 200

    decision_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/decide",
        json={"auto_apply": True, "operator": "release-bot"},
    )
    assert decision_resp.status_code == 200
    decision = decision_resp.json()
    assert decision["decision"] == "upgrade"
    assert decision["applied"] is True
    assert decision["updated_rollout_status"] == "full_released"

    list_resp = client.get("/api/artifacts/candidates", params={"user_id": "u-metrics"})
    assert list_resp.status_code == 200
    item = next(v for v in list_resp.json() if v["id"] == candidate_id)
    assert item["metadata"]["effect_metrics"]["summary"]["sample_size"] == 20


def test_artifact_factory_rollout_decision_can_trigger_rollback(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-rollback",
            "task_summary": "自动化测试编排",
            "repeat_count": 2,
            "tool_call_count": 2,
            "unique_tool_count": 2,
            "failure_rate": 0.03,
        },
    )
    assert decide_resp.status_code == 200
    candidate_id = decide_resp.json()["id"]

    approve_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/approve",
        json={"approver": "ops"},
    )
    assert approve_resp.status_code == 200
    transition_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={"target_status": "grayscale"},
    )
    assert transition_resp.status_code == 200

    for _ in range(20):
        metric_resp = client.post(
            f"/api/artifacts/candidates/{candidate_id}/metrics",
            json={
                "metrics": {
                    "success_rate": 0.80,
                    "error_rate": 0.15,
                    "latency_p95_ms": 3200,
                }
            },
        )
        assert metric_resp.status_code == 200

    decision_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/decide",
        json={"auto_apply": True},
    )
    assert decision_resp.status_code == 200
    payload = decision_resp.json()
    assert payload["decision"] == "rollback"
    assert payload["updated_rollout_status"] == "rolled_back"

    invalid_transition = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={"target_status": "full_released"},
    )
    assert invalid_transition.status_code == 400


def test_artifact_factory_records_decision_explanations(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-explain",
            "task_summary": "将工单分类并自动打标签",
            "repeat_count": 4,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.02,
            "metadata": {"biz_line": "support"},
        },
    )
    assert decide_resp.status_code == 200
    candidate = decide_resp.json()
    candidate_id = candidate["id"]
    assert candidate["metadata"]["decision_explanations"]

    explain_resp = client.get(
        f"/api/artifacts/candidates/{candidate_id}/decision-explanations"
    )
    assert explain_resp.status_code == 200
    payload = explain_resp.json()
    assert payload["candidate_id"] == candidate_id
    assert payload["count"] >= 1
    first = payload["items"][0]
    assert first["source"] == "manual"
    assert first["signals"]["repeat_count"] == 4
    assert first["decision"]["artifact_type"] == "skill"
    assert first["decision"]["scores"]["skill_score"] >= 1


def test_artifact_factory_dashboard_and_alert_events_api(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-dashboard",
            "task_summary": "自动化发布流水线",
            "repeat_count": 2,
            "tool_call_count": 3,
            "unique_tool_count": 2,
            "failure_rate": 0.03,
        },
    )
    assert decide_resp.status_code == 200
    candidate_id = decide_resp.json()["id"]

    approve_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/approve",
        json={"approver": "release"},
    )
    assert approve_resp.status_code == 200

    transition_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={"target_status": "grayscale", "operator": "release"},
    )
    assert transition_resp.status_code == 200

    metric_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/metrics",
        json={
            "reporter": "monitor",
            "metrics": {
                "success_rate": 0.82,
                "error_rate": 0.18,
                "latency_p95_ms": 3600,
                "quality_score": 0.68,
            },
        },
    )
    assert metric_resp.status_code == 200

    dashboard_resp = client.get(
        "/api/artifacts/dashboard",
        params={"user_id": "u-dashboard"},
    )
    assert dashboard_resp.status_code == 200
    dashboard = dashboard_resp.json()
    assert dashboard["overview"]["total_candidates"] >= 1
    assert dashboard["overview"]["materialized_count"] >= 1
    assert dashboard["alerts"]["total"] >= 1
    assert dashboard["candidate_snapshots"][0]["candidate_id"] == candidate_id

    alerts_resp = client.get(
        "/api/artifacts/alerts",
        params={"candidate_id": candidate_id},
    )
    assert alerts_resp.status_code == 200
    alerts_payload = alerts_resp.json()
    assert alerts_payload["count"] >= 2
    event_types = {item["event_type"] for item in alerts_payload["items"]}
    assert "rollout_transition" in event_types
    assert "metric_threshold" in event_types


def test_artifact_factory_supports_version_lineage_api(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    base_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-lineage",
            "task_summary": "自动工单分类",
            "repeat_count": 3,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.01,
        },
    )
    assert base_resp.status_code == 200
    base = base_resp.json()
    assert base["version"] == 1
    assert base["parent_candidate_id"] is None

    child_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-lineage",
            "parent_candidate_id": base["id"],
            "task_summary": "自动工单分类 v2",
            "repeat_count": 4,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.01,
        },
    )
    assert child_resp.status_code == 200
    child = child_resp.json()
    assert child["parent_candidate_id"] == base["id"]
    assert child["lineage_id"] == base["lineage_id"]
    assert child["version"] == 2

    lineage_resp = client.get(f"/api/artifacts/candidates/{child['id']}/lineage")
    assert lineage_resp.status_code == 200
    lineage = lineage_resp.json()
    assert lineage["count"] == 2
    assert [item["version"] for item in lineage["items"]] == [1, 2]
    assert lineage["items"][0]["id"] == base["id"]
    assert lineage["items"][1]["id"] == child["id"]


def test_artifact_factory_ab_routing_strategy_supports_control_and_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    base_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-ab",
            "task_summary": "知识库问答",
            "repeat_count": 2,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.02,
        },
    )
    base_id = base_resp.json()["id"]
    client.post(f"/api/artifacts/candidates/{base_id}/approve", json={"approver": "ops"})

    child_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-ab",
            "parent_candidate_id": base_id,
            "task_summary": "知识库问答-v2",
            "repeat_count": 2,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.02,
        },
    )
    child_id = child_resp.json()["id"]
    client.post(f"/api/artifacts/candidates/{child_id}/approve", json={"approver": "ops"})
    client.post(
        f"/api/artifacts/candidates/{child_id}/rollout/transition",
        json={"target_status": "grayscale"},
    )

    cfg_resp = client.post(
        f"/api/artifacts/candidates/{child_id}/ab-routing/config",
        json={"enabled": True, "control_ratio": 1.0, "salt": "test-salt"},
    )
    assert cfg_resp.status_code == 200

    route_resp = client.post(
        f"/api/artifacts/candidates/{child_id}/ab-routing/route",
        json={"subject_key": "user-1"},
    )
    assert route_resp.status_code == 200
    route_payload = route_resp.json()
    assert route_payload["bucket"] == "control"
    assert route_payload["target_candidate_id"] == base_id

    override_resp = client.post(
        f"/api/artifacts/candidates/{child_id}/ab-routing/route",
        json={"subject_key": "user-1", "force_bucket": "treatment"},
    )
    assert override_resp.status_code == 200
    override_payload = override_resp.json()
    assert override_payload["bucket"] == "treatment"
    assert override_payload["target_candidate_id"] == child_id


def test_artifact_factory_rollback_freeze_window_and_manual_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-freeze",
            "task_summary": "风控审批自动化",
            "repeat_count": 2,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.03,
        },
    )
    candidate_id = decide_resp.json()["id"]
    client.post(f"/api/artifacts/candidates/{candidate_id}/approve", json={"approver": "ops"})
    client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={"target_status": "grayscale"},
    )

    rollback_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={
            "target_status": "rolled_back",
            "operator": "release-bot",
            "freeze_window_minutes": 120,
            "reason": "error spike",
        },
    )
    assert rollback_resp.status_code == 200

    freeze_resp = client.get(f"/api/artifacts/candidates/{candidate_id}/rollout/freeze")
    assert freeze_resp.status_code == 200
    assert freeze_resp.json()["active"] is True

    blocked_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={"target_status": "grayscale"},
    )
    assert blocked_resp.status_code == 400
    assert "freeze" in blocked_resp.json()["detail"]

    override_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/freeze/override",
        json={"operator": "human-ops", "reason": "manual check passed"},
    )
    assert override_resp.status_code == 200

    resume_resp = client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={"target_status": "grayscale"},
    )
    assert resume_resp.status_code == 200
    assert resume_resp.json()["rollout_status"] == "grayscale"


def test_artifact_factory_week4_trajectory_clustering_discovers_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    copilot = copilot_module.get_copilot_service()

    session_ids = []
    for _ in range(3):
        session_resp = client.post("/api/copilot/sessions", json={})
        assert session_resp.status_code == 200
        session_id = session_resp.json()["session_id"]
        session_ids.append(session_id)
        session = asyncio.run(copilot.session_manager.get_session(session_id))
        assert session is not None
        session.metadata["user_id"] = "u-week4-cluster"
        asyncio.run(copilot.session_manager.save(session))
        asyncio.run(
            copilot.session_manager.add_message(
                session_id=session_id,
                role="user",
                content="请帮我做自动化日报汇总并输出固定模板",
            )
        )
        asyncio.run(
            copilot.session_manager.add_message(
                session_id=session_id,
                role="assistant",
                content="收到，我会调用工具处理。",
                tool_calls=[{"id": f"tc-{session_id}", "name": "report_tool", "arguments": "{}"}],
            )
        )

    cycle_resp = client.post(
        "/api/artifacts/learning/cycle",
        json={
            "user_id": "u-week4-cluster",
            "min_cluster_size": 2,
            "trigger_revision": False,
        },
    )
    assert cycle_resp.status_code == 200
    payload = cycle_resp.json()
    assert payload["trajectory_clustering"]["eligible_cluster_count"] >= 1
    assert payload["trajectory_clustering"]["created_count"] >= 1

    list_resp = client.get("/api/artifacts/candidates", params={"user_id": "u-week4-cluster"})
    assert list_resp.status_code == 200
    candidates = list_resp.json()
    assert any(
        (
            item.get("metadata", {}).get("signal_source") == "trajectory_cluster"
            and item.get("metadata", {}).get("trajectory_cluster", {}).get("cluster_size", 0) >= 2
        )
        for item in candidates
    )


def test_artifact_factory_week4_auto_revision_trigger_creates_child_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-week4-revision",
            "task_summary": "自动质检流水线",
            "repeat_count": 3,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.02,
        },
    )
    assert decide_resp.status_code == 200
    base_candidate_id = decide_resp.json()["id"]

    approve_resp = client.post(
        f"/api/artifacts/candidates/{base_candidate_id}/approve",
        json={"approver": "ops"},
    )
    assert approve_resp.status_code == 200

    for _ in range(15):
        metric_resp = client.post(
            f"/api/artifacts/candidates/{base_candidate_id}/metrics",
            json={
                "reporter": "monitor",
                "metrics": {
                    "success_rate": 0.72,
                    "error_rate": 0.18,
                    "latency_p95_ms": 4200,
                    "quality_score": 0.61,
                },
            },
        )
        assert metric_resp.status_code == 200

    cycle_resp = client.post(
        "/api/artifacts/learning/cycle",
        json={
            "user_id": "u-week4-revision",
            "min_cluster_size": 10,
            "trigger_revision": True,
            "min_revision_samples": 10,
            "revision_cooldown_hours": 1,
        },
    )
    assert cycle_resp.status_code == 200
    payload = cycle_resp.json()
    assert payload["auto_revision"]["triggered_count"] >= 1
    assert payload["auto_revision"]["created_count"] >= 1

    list_resp = client.get("/api/artifacts/candidates", params={"user_id": "u-week4-revision"})
    assert list_resp.status_code == 200
    candidates = list_resp.json()
    children = [
        item for item in candidates
        if item.get("parent_candidate_id") == base_candidate_id
        and item.get("metadata", {}).get("signal_source") == "auto_revision_trigger"
    ]
    assert children


def test_artifact_learning_cycle_respects_user_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    copilot = copilot_module.get_copilot_service()

    session_resp = client.post("/api/copilot/sessions", json={})
    assert session_resp.status_code == 200
    target_session_id = session_resp.json()["session_id"]
    target_session = asyncio.run(copilot.session_manager.get_session(target_session_id))
    assert target_session is not None
    target_session.metadata["user_id"] = "target-user"
    asyncio.run(copilot.session_manager.save(target_session))
    asyncio.run(
        copilot.session_manager.add_message(
            session_id=target_session_id,
            role="user",
            content="请帮我整理发票核对清单",
        )
    )

    other_session_resp = client.post("/api/copilot/sessions", json={})
    assert other_session_resp.status_code == 200
    other_session_id = other_session_resp.json()["session_id"]
    other_session = asyncio.run(copilot.session_manager.get_session(other_session_id))
    assert other_session is not None
    other_session.metadata["user_id"] = "other-user"
    asyncio.run(copilot.session_manager.add_message(
        session_id=other_session_id,
        role="user",
        content="请帮我整理发布审批表",
    ))
    asyncio.run(copilot.session_manager.save(other_session))

    cycle_resp = client.post(
        "/api/artifacts/learning/cycle",
        json={
            "user_id": "target-user",
            "dry_run": True,
            "trigger_revision": False,
        },
    )
    assert cycle_resp.status_code == 200
    payload = cycle_resp.json()
    assert payload["input"]["session_count"] == 1


def test_artifact_auto_revision_cooldown_blocks_after_materialized_child(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-week4-cooldown",
            "task_summary": "自动化测试流水线",
            "repeat_count": 3,
            "tool_call_count": 2,
            "unique_tool_count": 1,
        },
    )
    assert decide_resp.status_code == 200
    base_candidate_id = decide_resp.json()["id"]
    assert client.post(
        f"/api/artifacts/candidates/{base_candidate_id}/approve",
        json={"approver": "ops"},
    ).status_code == 200

    for _ in range(15):
        assert client.post(
            f"/api/artifacts/candidates/{base_candidate_id}/metrics",
            json={
                "metrics": {
                    "success_rate": 0.72,
                    "error_rate": 0.18,
                    "latency_p95_ms": 4200,
                    "quality_score": 0.61,
                }
            },
        ).status_code == 200

    first_cycle = client.post(
        "/api/artifacts/learning/cycle",
        json={
            "user_id": "u-week4-cooldown",
            "trigger_revision": True,
            "min_revision_samples": 10,
            "revision_cooldown_hours": 24,
            "min_cluster_size": 10,
        },
    )
    assert first_cycle.status_code == 200
    first_payload = first_cycle.json()
    assert first_payload["auto_revision"]["created_count"] >= 1

    items = client.get("/api/artifacts/candidates", params={"user_id": "u-week4-cooldown"}).json()
    child = next(
        item for item in items
        if item.get("parent_candidate_id") == base_candidate_id
    )
    assert client.post(
        f"/api/artifacts/candidates/{child['id']}/approve",
        json={"approver": "ops"},
    ).status_code == 200

    second_cycle = client.post(
        "/api/artifacts/learning/cycle",
        json={
            "user_id": "u-week4-cooldown",
            "trigger_revision": True,
            "min_revision_samples": 10,
            "revision_cooldown_hours": 24,
            "min_cluster_size": 10,
        },
    )
    assert second_cycle.status_code == 200
    second_payload = second_cycle.json()
    blocked = [
        item for item in second_payload["auto_revision"]["items"]
        if item.get("candidate_id") == base_candidate_id and item.get("reason") == "cooldown_active"
    ]
    assert blocked


def test_artifact_learning_cycle_can_auto_create_controlled_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_AUTO_CREATE_ENABLED", "true")
    monkeypatch.setenv("ARTIFACT_ASSESS_TOOL_CALL_TARGET", "2")
    _reset_singletons()

    client = TestClient(create_app())
    copilot = copilot_module.get_copilot_service()
    for _ in range(3):
        session_resp = client.post("/api/copilot/sessions", json={})
        assert session_resp.status_code == 200
        session_id = session_resp.json()["session_id"]
        session = asyncio.run(copilot.session_manager.get_session(session_id))
        assert session is not None
        session.metadata["user_id"] = "u-auto-create"
        asyncio.run(copilot.session_manager.save(session))
        asyncio.run(
            copilot.session_manager.add_message(
                session_id=session_id,
                role="user",
                content="帮我把日报转换为固定结构输出",
            )
        )
        asyncio.run(
            copilot.session_manager.add_message(
                session_id=session_id,
                role="assistant",
                content="开始处理",
                tool_calls=[
                    {"id": f"tc-{session_id}-1", "name": "fetch_data", "arguments": "{}"},
                    {"id": f"tc-{session_id}-2", "name": "normalize_data", "arguments": "{}"},
                ],
            )
        )

    cycle_resp = client.post(
        "/api/artifacts/learning/cycle",
        json={
            "user_id": "u-auto-create",
            "min_cluster_size": 2,
            "trigger_revision": False,
            "trigger_auto_create": True,
            "auto_create_limit": 3,
        },
    )
    assert cycle_resp.status_code == 200
    payload = cycle_resp.json()
    assert payload["auto_controlled_creation"]["auto_created_count"] >= 1

    list_resp = client.get("/api/artifacts/candidates", params={"user_id": "u-auto-create"})
    assert list_resp.status_code == 200
    candidates = list_resp.json()
    auto_items = [
        item for item in candidates
        if item.get("metadata", {}).get("creation_mode") == "auto_controlled"
    ]
    assert auto_items
    first = auto_items[0]
    assert first["status"] == "materialized"
    assert first["rollout_status"] == "grayscale"
    assert first.get("metadata", {}).get("rollout_guard") == "grayscale_only"


def test_artifact_learning_cycle_auto_create_disabled_by_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_AUTO_CREATE_ENABLED", "false")
    _reset_singletons()

    client = TestClient(create_app())
    copilot = copilot_module.get_copilot_service()
    for _ in range(2):
        session_resp = client.post("/api/copilot/sessions", json={})
        assert session_resp.status_code == 200
        session_id = session_resp.json()["session_id"]
        session = asyncio.run(copilot.session_manager.get_session(session_id))
        assert session is not None
        session.metadata["user_id"] = "u-auto-disabled"
        asyncio.run(copilot.session_manager.save(session))
        asyncio.run(
            copilot.session_manager.add_message(
                session_id=session_id,
                role="user",
                content="请把日报信息整理成结构化输出",
            )
        )

    cycle_resp = client.post(
        "/api/artifacts/learning/cycle",
        json={
            "user_id": "u-auto-disabled",
            "min_cluster_size": 2,
            "trigger_revision": False,
            "trigger_auto_create": True,
            "auto_create_limit": 3,
        },
    )
    assert cycle_resp.status_code == 200
    payload = cycle_resp.json()
    assert payload["auto_controlled_creation"]["auto_created_count"] == 0


def test_artifact_rollout_auto_manage_applies_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-r4",
            "task_summary": "工单聚类与回复",
            "repeat_count": 3,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.02,
        },
    )
    assert decide_resp.status_code == 200
    candidate_id = decide_resp.json()["id"]

    assert client.post(
        f"/api/artifacts/candidates/{candidate_id}/approve",
        json={"approver": "ops"},
    ).status_code == 200
    assert client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={"target_status": "grayscale", "operator": "ops"},
    ).status_code == 200

    for _ in range(20):
        metric_resp = client.post(
            f"/api/artifacts/candidates/{candidate_id}/metrics",
            json={
                "metrics": {
                    "success_rate": 0.99,
                    "error_rate": 0.01,
                    "latency_p95_ms": 1500,
                }
            },
        )
        assert metric_resp.status_code == 200

    auto_resp = client.post(
        "/api/artifacts/rollout/auto-manage",
        json={"user_id": "u-r4", "auto_apply": True, "operator": "rollout-bot"},
    )
    assert auto_resp.status_code == 200
    payload = auto_resp.json()
    assert payload["summary"]["selected_count"] >= 1
    assert payload["summary"]["applied_count"] >= 1
    item = next(x for x in payload["items"] if x["candidate_id"] == candidate_id)
    assert item["decision"] == "upgrade"
    assert item["updated_rollout_status"] == "full_released"


def test_artifact_rollout_auto_manage_dry_run_no_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    decide_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-r4-dry",
            "task_summary": "自动分诊",
            "repeat_count": 3,
            "tool_call_count": 2,
            "unique_tool_count": 1,
            "failure_rate": 0.02,
        },
    )
    assert decide_resp.status_code == 200
    candidate_id = decide_resp.json()["id"]

    assert client.post(
        f"/api/artifacts/candidates/{candidate_id}/approve",
        json={"approver": "ops"},
    ).status_code == 200
    assert client.post(
        f"/api/artifacts/candidates/{candidate_id}/rollout/transition",
        json={"target_status": "grayscale", "operator": "ops"},
    ).status_code == 200

    for _ in range(20):
        metric_resp = client.post(
            f"/api/artifacts/candidates/{candidate_id}/metrics",
            json={
                "metrics": {
                    "success_rate": 0.99,
                    "error_rate": 0.01,
                    "latency_p95_ms": 1400,
                }
            },
        )
        assert metric_resp.status_code == 200

    auto_resp = client.post(
        "/api/artifacts/rollout/auto-manage",
        json={
            "user_id": "u-r4-dry",
            "auto_apply": True,
            "dry_run": True,
            "operator": "rollout-bot",
        },
    )
    assert auto_resp.status_code == 200
    payload = auto_resp.json()
    item = next(x for x in payload["items"] if x["candidate_id"] == candidate_id)
    assert item["decision"] == "upgrade"
    assert item["applied"] is False

    list_resp = client.get("/api/artifacts/candidates", params={"user_id": "u-r4-dry"})
    assert list_resp.status_code == 200
    latest = next(v for v in list_resp.json() if v["id"] == candidate_id)
    assert latest["rollout_status"] == "grayscale"


def test_artifact_export_sharegpt(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    copilot = copilot_module.get_copilot_service()

    session_resp = client.post("/api/copilot/sessions", json={})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["session_id"]
    session = asyncio.run(copilot.session_manager.get_session(session_id))
    assert session is not None
    session.metadata["user_id"] = "u-export"
    session.metadata["portal_id"] = "p-export"
    session.workflow_id = "wf-export"
    asyncio.run(copilot.session_manager.save(session))
    asyncio.run(
        copilot.session_manager.add_message(
            session_id=session_id,
            role="user",
            content="请帮我总结今天的工作进展",
        )
    )
    asyncio.run(
        copilot.session_manager.add_message(
            session_id=session_id,
            role="assistant",
            content="今天完成了需求分析、接口设计和联调准备。",
        )
    )

    export_resp = client.post(
        "/api/artifacts/export/sharegpt",
        json={
            "user_id": "u-export",
            "portal_id": "p-export",
            "workflow_id": "wf-export",
            "min_quality_score": 0.1,
            "limit": 10,
            "max_sessions": 100,
        },
    )
    assert export_resp.status_code == 200
    payload = export_resp.json()
    assert payload["format"] == "sharegpt"
    assert payload["count"] >= 1
    item = payload["items"][0]
    assert item["meta"]["session_id"] == session_id
    assert item["meta"]["user_id"] == "u-export"
    assert item["meta"]["portal_id"] == "p-export"
    assert item["meta"]["workflow_id"] == "wf-export"
    assert isinstance(item["conversations"], list) and len(item["conversations"]) >= 2
    assert item["conversations"][0]["from"] == "human"


def test_artifact_transfer_recommendations(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    _reset_singletons()

    client = TestClient(create_app())
    portal_resp = client.get("/api/portals/default")
    assert portal_resp.status_code == 200
    target_portal_id = portal_resp.json()["id"]

    match_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-transfer",
            "task_summary": "客服工单自动分诊与回复生成",
            "repeat_count": 4,
            "tool_call_count": 3,
            "unique_tool_count": 2,
            "failure_rate": 0.02,
            "metadata": {"source_portal_id": "source-a"},
        },
    )
    assert match_resp.status_code == 200
    non_match_resp = client.post(
        "/api/artifacts/decide",
        json={
            "user_id": "u-transfer",
            "task_summary": "视频转场与剪辑脚本生成",
            "repeat_count": 1,
            "tool_call_count": 1,
            "unique_tool_count": 1,
            "failure_rate": 0.08,
            "metadata": {"source_portal_id": "source-b"},
        },
    )
    assert non_match_resp.status_code == 200

    rec_resp = client.post(
        "/api/artifacts/transfer/recommendations",
        json={
            "target_portal_id": target_portal_id,
            "user_id": "u-transfer",
            "top_k": 5,
            "min_score": 0.0,
            "include_pending": True,
        },
    )
    assert rec_resp.status_code == 200
    payload = rec_resp.json()
    assert payload["count"] >= 1
    top = payload["items"][0]
    assert top["candidate_id"] == match_resp.json()["id"]
    assert top["recommendation"] == "review_then_bind_to_target_portal"
    assert top["score"] >= 0
