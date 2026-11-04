import io
import zipfile
import pytest
from cim.service import FactoryService,Conflict
from test_workflow import returned


def approve_all_tasks(s,pid):
    p=s.detail(pid)["project"]
    s.confirm_requirements(pid,p["revision"],"需求责任人")
    s.plan_tasks(pid,p["revision"])
    while True:
        pending=[t for t in s.detail(pid)["tasks"] if t["status"]!="approved"]
        if not pending: return
        progressed=False
        for task in pending:
            try:
                a=s.start_attempt(pid,task["id"],"complete-"+task["id"])
            except Conflict:
                continue
            s.submit_result(pid,returned(a))
            s.review_task(pid,task["id"],"approve","独立评审人","离线测试夹具，非现场审批")
            progressed=True
        assert progressed


def test_implemented_archive_requires_each_evidence_layer_and_preserves_observation_state(tmp_path):
    s=FactoryService(tmp_path/"business")
    p=s.create_project("Offline lifecycle",classification="internal",requirements="离线生命周期评测",equipment="LUL")
    pid=p["id"]
    approve_all_tasks(s,pid)
    evidence=s.add_document(pid,1,"TEST_ONLY_verification.txt",b"Synthetic test evidence, not GX or field acceptance",kind="evidence",classification="internal")
    comparison={"baseline":"fixture","after":"pending","metric_definition":"fixture count", "product_recipe":"TEST", "window":"TEST",
                "effect_status":"pending_observation","confounders":[],"source_ids":[]}
    kwargs=dict(outcome="implemented",reason="离线业务状态测试",comparison=comparison,actual_investment={},remaining=["现场观察"],actor="测试执行人")
    with pytest.raises(Conflict): s.archive(pid,1,**kwargs)
    for phase in ["static","compile","simulation","field"]:
        s.verification(pid,1,phase=phase,status="passed",actor="测试夹具",record="仅验证业务状态机；不声称真实运行",source_ids=[evidence["id"]])
    a=s.archive(pid,1,**kwargs)
    assert a["comparison"]["effect_status"]=="pending_observation"
    with zipfile.ZipFile(io.BytesIO(s.archive_bundle(pid))) as z:
        assert z.read("files/"+evidence["id"]+".txt").startswith(b"Synthetic")


def test_shared_case_requires_review_and_matches_area_and_cpu(tmp_path):
    s=FactoryService(tmp_path/"business")
    source=s.create_project("Shared source",classification="internal",area="FA",cpu="Q26UDV",equipment="LUL")
    d=s.add_document(source["id"],1,"case.md","专属玻璃搬送握手案例".encode(),classification="internal")
    with pytest.raises(Conflict): s.publish_case(source["id"],"复核人","适用 FA Q26UDV")
    s.archive(source["id"],2,outcome="not_implemented",reason="仅供案例检索评测",comparison={},actual_investment={},remaining=[],actor="归档人")
    share=s.publish_case(source["id"],"复核人","适用 FA Q26UDV LUL 的问题案例，非通过案例")
    same=s.create_project("same",classification="internal",area="FA",cpu="Q26UDV",equipment="LUL")
    wrong=s.create_project("wrong",classification="internal",area="ARRAY",cpu="R04CPU")
    assert not s.search(same["id"],"玻璃搬送")["citations"]
    assert s.search(same["id"],"玻璃搬送",include_shared=True)["citations"][0]["source_id"]==d["id"]
    assert not s.search(wrong["id"],"玻璃搬送",include_shared=True)["citations"]
    tasks=s.plan_tasks(same["id"],1)
    a=s.start_attempt(same["id"],tasks[0]["id"],"shared-attempt-001")
    assert any(x["id"]==d["id"] for x in a["contract"]["input_snapshot"]["sources"])
    s.submit_result(same["id"],returned(a,citations=[{"source_id":d["id"],"sha256":d["sha256"],"location":"line:1"}]))
    s.withdraw_case(source["id"],share["id"],"复核人","发现适用性问题")
    assert s.detail(same["id"])["project"]["revision"]==2
    assert not s.search(same["id"],"玻璃搬送",include_shared=True)["citations"]
    with pytest.raises(PermissionError): s.bundle(same["id"],a["id"])
