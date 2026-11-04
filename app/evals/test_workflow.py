import concurrent.futures
import hashlib
import io
import json
import zipfile
import pytest
from cim.service import FactoryService,Conflict
from cim.mcp import FactoryTools


@pytest.fixture
def service(tmp_path):
    return FactoryService(tmp_path/"business")


def project(service,level="internal"):
    return service.create_project("测试项目",classification=level,requirements="范围：一台 LUL，马达负载 FDC；验证单位、周期和断线行为",equipment="LUL")


def first_attempt(service,p):
    tasks=service.plan_tasks(p["id"],p["revision"])
    t=next(x for x in tasks if x["stage"]=="requirements")
    return t,service.start_attempt(p["id"],t["id"],"stable-request-001")


def returned(a,**changes):
    c=a["contract"]
    return {**{k:c[k] for k in ["project_id","task_id","attempt_id","input_revision","snapshot_hash"]},
            "summary":"范围待确认，工艺约束缺项已列出","verdict":"candidate","citations":[],"questions":[],"findings":[],"artifacts":[],**changes}


def test_empty_requirement_cannot_be_confirmed(service):
    p=service.create_project("空需求",classification="internal")
    with pytest.raises(ValueError):
        service.confirm_requirements(p["id"],1,"工程师")


def test_manual_bundle_preserves_original_bytes_and_skill_versions(service):
    p=project(service)
    raw="马达负载\tD100\r\n".encode("utf-16")
    d=service.add_document(p["id"],1,"点表.csv",raw,classification="internal")
    p=service.detail(p["id"])["project"]
    t,a=first_attempt(service,p)
    bundle=service.bundle(p["id"],a["id"])
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        assert z.read("sources/"+d["id"]+".csv")==raw
        c=json.loads(z.read("task.json"))
        assert c["input_revision"]==2 and c["definition"]["skills"][0]["instructions"]
        assert c["tools"]==["knowledge.search","evidence.read"]
    with pytest.raises(PermissionError):
        service.bundle(p["id"],a["id"],"external")


def test_revision_change_marks_old_tasks_and_return_stale(service):
    p=project(service)
    t,a=first_attempt(service,p)
    service.update_project(p["id"],1,requirements="新增机台，原范围无效")
    r=service.submit_result(p["id"],returned(a))
    assert r["stale"] and not r["accepted"]
    assert next(t for t in service.detail(p["id"])["tasks"] if t["id"]==a["task_id"])["status"]=="stale"
    with pytest.raises(Conflict):
        service.review_task(p["id"],t["id"],"approve","评审人","旧资料不能接受")
    with pytest.raises(Conflict):
        service.update_project(p["id"],1,requirements="并发旧版本")


def test_idempotent_start_and_return_survive_restart(service):
    p=project(service)
    t,a=first_attempt(service,p)
    resumed=FactoryService(service.root)
    assert resumed.start_attempt(p["id"],t["id"],"stable-request-001")==a
    r=resumed.submit_result(p["id"],returned(a))
    assert resumed.submit_result(p["id"],returned(a))==r
    with pytest.raises(Conflict):
        resumed.submit_result(p["id"],returned(a,summary="不同内容不能覆盖"))


def test_concurrent_start_request_creates_one_attempt(service):
    p=project(service)
    tasks=service.plan_tasks(p["id"],1)
    t=tasks[0]
    def start(_):
        return service.start_attempt(p["id"],t["id"],"concurrent-key-001")["id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        ids=list(pool.map(start,range(4)))
    assert len(set(ids))==1 and len(service.detail(p["id"])["attempts"])==1


def test_dependencies_pause_and_manual_review_gate(service):
    p=project(service)
    tasks=service.plan_tasks(p["id"],1)
    baseline=next(t for t in tasks if t["stage"]=="baseline")
    with pytest.raises(Conflict):
        service.start_attempt(p["id"],baseline["id"],"baseline-req-001")
    service.confirm_requirements(p["id"],1,"需求人")
    for t in [t for t in tasks if t["stage"]=="requirements"]:
        a=service.start_attempt(p["id"],t["id"],"req-"+t["id"])
        service.submit_result(p["id"],returned(a))
        service.review_task(p["id"],t["id"],"approve","评审人","确认范围与证据")
    service.project_status(p["id"],"paused")
    with pytest.raises(Conflict):
        service.start_attempt(p["id"],baseline["id"],"baseline-req-001")
    service.project_status(p["id"],"active")
    assert service.start_attempt(p["id"],baseline["id"],"baseline-req-001")["status"]=="waiting_return"


def test_rework_and_cancellation_cannot_be_resurrected_by_late_result(service):
    p=project(service)
    t,a=first_attempt(service,p)
    service.review_task(p["id"],t["id"],"rework","评审人","缺少资料，原批次作废")
    late=service.submit_result(p["id"],returned(a))
    assert late["stale"]
    new=service.start_attempt(p["id"],t["id"],"rework-request-002")
    assert new["id"]!=a["id"]
    service.review_task(p["id"],t["id"],"cancel","评审人","任务取消")
    assert service.submit_result(p["id"],returned(new))["stale"]


def test_forged_contract_or_cross_project_evidence_is_rejected(service):
    p=project(service)
    q=project(service)
    d=service.add_document(q["id"],1,"秘密.md","马达负载：其他设备地址".encode(),classification="restricted")
    t,a=first_attempt(service,p)
    with pytest.raises(Conflict):
        service.submit_result(p["id"],returned(a,snapshot_hash="fake"))
    with pytest.raises(ValueError):
        service.submit_result(p["id"],returned(a,citations=[{"source_id":d["id"],"sha256":d["sha256"],"location":"line:1"}]))
    with pytest.raises(PermissionError):
        service.read_document(p["id"],d["id"])
    assert not service.search(p["id"],"马达负载")["citations"]


def test_private_rag_quotes_exact_coordinates_and_respects_revocation(service):
    p=project(service)
    raw="马达负载上报，单位需由点表确认。\n断线时保留历史值并标注无效。".encode()
    d=service.add_document(p["id"],1,"FDC.md",raw,classification="internal")
    hits=service.search(p["id"],"马达负载")["citations"]
    assert hits[0]["sha256"]==hashlib.sha256(raw).hexdigest() and hits[0]["location"]=="line:1"
    assert hits[0]["source_id"]==d["id"]
    service.revoke_document(p["id"],d["id"],2,"版本失效")
    assert not service.search(p["id"],"马达负载")["citations"]
    with pytest.raises(PermissionError):
        service.read_document(p["id"],d["id"])


def test_pending_classification_blocks_bundle_until_explicit_change(service):
    p=project(service,"public")
    d=service.add_document(p["id"],1,"待分级.md",b"private evidence",classification="pending")
    p=service.detail(p["id"])["project"]
    tasks=service.plan_tasks(p["id"],p["revision"])
    with pytest.raises(PermissionError):
        service.start_attempt(p["id"],tasks[0]["id"],"pending-request-001")
    service.classify_document(p["id"],d["id"],2,"internal","资料责任人","经确认仅限厂内")
    with pytest.raises(PermissionError):
        service.read_document(p["id"],d["id"],"external")


def test_mcp_default_external_cannot_read_internal_or_invoke_admin(service):
    p=project(service)
    adapter=FactoryTools(service,p["id"])
    with pytest.raises(PermissionError):
        adapter.call("factory_project",{})
    assert adapter.call("factory_catalog",{})["json_chunk"]
    internal=FactoryTools(service,p["id"],trusted_internal=True)
    assert internal.call("factory_project",{})["complete"]
    with pytest.raises(ValueError):
        internal.call("archive",{})


def test_partial_costs_stay_unknown_and_archive_cannot_fake_validation(service):
    p=project(service)
    data={"bom":[{"spec":"实际传感器","action":"new","quantity":2,"unit_price":None}],
          "labor":{"programming":1,"testing":2},"daily_rate":1000,
          "benefit":{"kind":"estimated","annual_value":10000,"basis":"演示计算，非实测"},"assumptions":[]}
    r=service.save_estimate(p["id"],1,data)
    assert r["result"]["known_cost_subtotal"]==3000 and r["result"]["total_cost"] is None
    assert r["result"]["payback_years"] is None
    assert r["result"]["person_days"] is None and r["result"]["known_person_days"]==3
    with pytest.raises(Conflict):
        service.archive(p["id"],1,outcome="implemented",reason="做完了",comparison={},actual_investment={},remaining=[],actor="归档人")
    with pytest.raises(ValueError):
        service.verification(p["id"],1,phase="compile",status="passed",actor="工程师",record="口头说通过",source_ids=[])
    archived=service.archive(p["id"],1,outcome="not_implemented",reason="数据不足，保留估算与缺项",comparison={},actual_investment={},remaining=["补日志"],actor="归档人")
    assert archived["outcome"]=="not_implemented"
    with zipfile.ZipFile(io.BytesIO(service.archive_bundle(p["id"]))) as z:
        assert "manifest.json" in z.namelist()
    with pytest.raises(PermissionError):
        service.archive_bundle(p["id"],"external")


def test_readonly_service_denies_mutation(service):
    readonly=FactoryService(service.root,read_only=True)
    with pytest.raises(PermissionError):
        project(readonly)


def test_engineering_fingerprint_change_makes_return_historical(service):
    class Projects:
        value={"id":"v1","ir_sha256":"hash-original"}
        def raw_version(self,pid,vid):
            return dict(self.value)
    class Engineering:
        projects=Projects()
    service.engineering=Engineering()
    p=project(service)
    service.link_engineering(p["id"],1,"eng1","v1")
    p=service.detail(p["id"])["project"]
    t,a=first_attempt(service,p)
    service.engineering.projects.value["ir_sha256"]="hash-changed"
    r=service.submit_result(p["id"],returned(a))
    assert r["stale"] and not r["accepted"]
    assert next(x for x in service.detail(p["id"])["tasks"] if x["id"]==t["id"])["status"]=="stale"
