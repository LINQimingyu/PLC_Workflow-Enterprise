"""Navigation acceptance uses isolated synthetic records, never PLC evidence."""
import json

import pytest
from fastapi.testclient import TestClient

from cim.service import FactoryService, STAGES
from integrations.web.app import create_app


@pytest.fixture
def service(tmp_path):
    return FactoryService(tmp_path / "business")


def project(service, classification="internal"):
    return service.create_project("流程导航测试夹具", classification=classification,
                                  requirements="仅测试业务状态，不代表真实编译或现场验收", equipment="LUL")


def returned(attempt, verdict="candidate"):
    contract = attempt["contract"]
    return {**{k: contract[k] for k in ("project_id", "task_id", "attempt_id", "input_revision", "snapshot_hash")},
            "summary": "隔离业务验收夹具", "verdict": verdict, "citations": [], "questions": [], "findings": [], "artifacts": []}


def approve(service, p, task):
    attempt = service.start_attempt(p["id"], task["id"], "fixture-" + task["id"])
    service.submit_result(p["id"], returned(attempt))
    service.review_task(p["id"], task["id"], "approve", "夹具审查人", "仅验收状态流转")


def planned(service, p):
    service.confirm_requirements(p["id"], p["revision"], "夹具需求人")
    return service.plan_tasks(p["id"], p["revision"])


def item(snapshot, key):
    return next(n for n in snapshot["nodes"] if n["id"] == key)


def test_new_project_and_reads_do_not_modify_any_records(service):
    p = project(service)
    with service.connect() as db:
        before = list(db.iterdump())
    first = service.workflow(p["id"])
    service.workflow(p["id"])
    service.workflow_history(p["id"])
    with service.connect() as db:
        assert list(db.iterdump()) == before
    assert first["current_stage"] == "requirements"
    assert first["recommended"]["focus"] == "requirements"
    assert len([n for n in first["nodes"] if n["kind"] == "stage"]) == 7
    assert len([n for n in first["nodes"] if n["kind"] == "verification"]) == 5
    assert first["recent_completed"] is None


def test_confirmation_is_separate_from_parallel_requirement_experts(service):
    p = project(service)
    service.confirm_requirements(p["id"], 1, "需求人")
    assert service.workflow(p["id"])["recommended"]["focus"] == "plan"
    tasks = service.plan_tasks(p["id"], 1)
    snap = service.workflow(p["id"])
    assert item(snap, "requirements:confirm")["status"] == "completed"
    assert snap["current_stage"] == "requirements"
    requirement_tasks = [t for t in tasks if t["stage"] == "requirements"]
    assert len(snap["todo"]) == len(requirement_tasks) == 2
    for t in requirement_tasks:
        assert item(snap, "task:" + t["id"])["ready"]
        approve(service, p, t)
    assert service.workflow(p["id"])["current_stage"] == "baseline"
    baseline = next(t for t in tasks if t["stage"] == "baseline")
    assert service.workflow(p["id"])["recommended"]["task_id"] == baseline["id"]


def test_waiting_return_review_and_rework_recommend_actual_batch(service):
    p = project(service)
    tasks = planned(service, p)
    requirements = [t for t in tasks if t["stage"] == "requirements"]
    attempts = [service.start_attempt(p["id"], t["id"], "wait-" + t["id"]) for t in requirements]
    snap = service.workflow(p["id"])
    assert snap["recommended"]["label"] == "载入任务回传"
    service.submit_result(p["id"], returned(attempts[0]))
    assert service.workflow(p["id"])["recommended"]["label"] == "审查当前回传"
    service.review_task(p["id"], requirements[0]["id"], "rework", "审查人", "补充依据")
    snap = service.workflow(p["id"])
    n = item(snap, "task:" + requirements[0]["id"])
    assert n["status"] == "rework" and n["ready"]
    assert snap["recommended"]["task_id"] == requirements[0]["id"]
    assert any("补充依据" in a["label"] for a in n["outputs"])


@pytest.mark.parametrize("verdict", ["needs_info", "failed"])
def test_failure_and_missing_information_are_not_completed(service, verdict):
    p = project(service)
    task = planned(service, p)[0]
    attempt = service.start_attempt(p["id"], task["id"], "fixture-missing")
    service.submit_result(p["id"], returned(attempt, verdict))
    snap = service.workflow(p["id"])
    assert item(snap, "task:" + task["id"])["status"] == verdict
    assert snap["recommended"]["task_id"] == task["id"]


def test_input_change_preserves_history_without_lighting_new_version(service):
    p = project(service)
    tasks = planned(service, p)
    approve(service, p, tasks[0])
    service.add_document(p["id"], 1, "new-source.md", b"new baseline", classification="internal")
    snap = service.workflow(p["id"])
    assert snap["revision"] == 2 and snap["historical_tasks"] == len(tasks)
    assert not any(n["kind"] == "task" for n in snap["nodes"])
    assert item(snap, "stage:requirements")["completed"] == 0
    assert snap["recent_completed"]["revision"] == 1
    service.confirm_requirements(p["id"], 2, "新确认人")
    assert service.workflow(p["id"])["recommended"]["focus"] == "plan"


def test_pause_pending_classification_and_engineering_drift_take_priority(service, monkeypatch):
    p = project(service, "pending")
    tasks = planned(service, p)
    assert service.workflow(p["id"])["recommended"]["focus"] == "classification"
    assert not item(service.workflow(p["id"]), "task:" + tasks[0]["id"])["ready"]
    service.project_status(p["id"], "paused")
    assert service.workflow(p["id"])["recommended"]["focus"] == "project"
    service.project_status(p["id"], "active")
    monkeypatch.setattr(service, "_engineering_current", lambda p: False)
    snap = service.workflow(p["id"])
    assert snap["recommended"]["focus"] == "engineering"
    assert all(not n["ready"] for n in snap["nodes"] if n["kind"] == "task")


def test_cancelled_tasks_do_not_count_as_approved_or_unblock_dependents(service):
    p = project(service)
    tasks = planned(service, p)
    service.review_task(p["id"], tasks[0]["id"], "cancel", "审查人", "夹具取消")
    snap = service.workflow(p["id"])
    assert item(snap, "stage:requirements")["status"] != "completed"
    baseline = next(t for t in tasks if t["stage"] == "baseline")
    n = item(snap, "task:" + baseline["id"])
    assert not n["ready"] and "前置任务尚未审查通过" in n["blockers"]


def test_engineering_drift_marks_approvals_stale_without_rewriting_them(service, monkeypatch):
    p = project(service)
    task = planned(service, p)[0]
    approve(service, p, task)
    monkeypatch.setattr(service, "_engineering_current", lambda p: False)
    snap = service.workflow(p["id"])
    assert item(snap, "task:" + task["id"])["status"] == "stale"
    assert next(t for t in service.detail(p["id"])["tasks"] if t["id"] == task["id"])["status"] == "approved"


def test_latest_verification_and_reasoned_exemption(service):
    p = project(service)
    service.verification(p["id"], 1, phase="compile", status="not_applicable", actor="夹具", record="仅测试豁免，不产生编译证据", source_ids=[])
    assert item(service.workflow(p["id"]), "verification:compile")["status"] == "not_applicable"
    service.project_status(p["id"], "paused")
    assert item(service.workflow(p["id"]), "verification:compile")["status"] == "not_applicable"
    service.project_status(p["id"], "active")
    service.verification(p["id"], 1, phase="compile", status="failed", actor="夹具", record="最新失败应覆盖先前豁免", source_ids=[])
    snap = service.workflow(p["id"])
    assert item(snap, "verification:compile")["status"] == "failed"
    assert item(snap, "stage:verification")["status"] == "failed"
    service.update_project(p["id"], 1, requirements="新版本")
    assert item(service.workflow(p["id"]), "verification:compile")["status"] == "not_run"


@pytest.mark.parametrize("outcome", ["implemented", "not_implemented", "cancelled"])
def test_archive_outcomes_and_effect_observation_are_explicit(service, outcome):
    p = project(service)
    comparison = {}
    if outcome == "implemented":
        tasks = planned(service, p)
        for t in sorted(tasks, key=lambda t: STAGES.index(t["stage"])):
            approve(service, p, t)
        assert service.workflow(p["id"])["current_stage"] == "verification"
        assert service.workflow(p["id"])["recommended"]["phase"] == "static"
        for phase in ("static", "compile", "simulation", "field"):
            service.verification(p["id"], 1, phase=phase, status="not_applicable", actor="隔离夹具", record="业务规则测试中的豁免，非实际工程验收", source_ids=[])
        snap = service.workflow(p["id"])
        assert item(snap, "stage:verification")["status"] == "completed"
        assert item(snap, "verification:benefit")["status"] == "not_run"
        comparison = dict(baseline="夹具", after="", metric_definition="夹具", product_recipe="夹具", window="夹具", effect_status="pending_observation", confounders=[], source_ids=[])
    service.archive(p["id"], 1, outcome=outcome, reason="隔离业务验收", comparison=comparison, actual_investment={}, remaining=[], actor="夹具归档人")
    snap = service.workflow(p["id"])
    assert snap["current_stage"] == "archive" and snap["todo"] == []
    assert snap["outcome"]["outcome"] == outcome
    assert item(snap, "archive:formal")["status"] == "completed"
    if outcome == "implemented":
        assert snap["outcome"]["effect_status"] == "pending_observation"
    else:
        assert item(snap, "stage:requirements")["status"] != "completed"


def test_history_pagination_keeps_legacy_contract_and_unknown_metadata(service):
    p = project(service)
    for i in range(44):
        service.project_status(p["id"], "paused" if i % 2 == 0 else "active")
    all_events = service.audit(p["id"])
    assert all_events[0]["seq"] < all_events[-1]["seq"]
    first = service.workflow_history(p["id"], limit=20)
    second = service.workflow_history(p["id"], limit=20, before_seq=first[-1]["seq"])
    assert len(first) == len(second) == 20
    assert not {e["seq"] for e in first} & {e["seq"] for e in second}
    assert first[0]["seq"] > second[0]["seq"]
    assert first[0]["revision"] == 1 and first[0]["actor"] is None
    with service.connect(True) as db:
        db.execute("INSERT INTO audit(at,project,action,data) VALUES(?,?,?,?)", ("2020-01-01T00:00:00Z", p["id"], "project.status", json.dumps({"status": "active"})))
    legacy = service.workflow_history(p["id"], limit=1)[0]
    assert legacy["actor"] is None and legacy["revision"] is None


def test_navigation_http_auth_pagination_validation_and_readonly(service, tmp_path):
    origin = "http://127.0.0.1:8772"
    app = create_app(tmp_path / "engineering", origin=origin, operator_token="fixture-only", read_only=True)
    with TestClient(app, base_url=origin) as client:
        p = FactoryService(app.state.factory.root).create_project("隔离只读导航", classification="internal")
        url = f"/api/cim/projects/{p['id']}"
        assert client.get(url + "/workflow").status_code == 401
        client.post("/api/session", json={"token": "fixture-only"})
        flow = client.get(url + "/workflow")
        assert flow.status_code == 200 and "只读" in flow.json()["blockers"][0]
        assert set(client.get(url + "/audit").json()) == {"events"}
        assert "next_before_seq" in client.get(url + "/audit?limit=20").json()
        assert client.get(url + "/audit?limit=0").status_code == 422
        assert client.get(url + "/audit?before_seq=-1").status_code == 422
