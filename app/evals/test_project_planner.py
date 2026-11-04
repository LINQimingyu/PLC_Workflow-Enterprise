"""Creation-agent contracts use fake models/keys, not paid provider requests."""
import concurrent.futures
import json

import pytest
from fastapi.testclient import TestClient

from cim.guide import workflow_guide
from cim.planner import PlannerError
from cim.policy import PolicyDenied
from cim.records import Conflict
from cim.service import FactoryService
from integrations.web.app import create_app


class Secrets:
    def __init__(self): self.values={}
    def read(self,target): return self.values.get(target,"")
    def write(self,target,value): self.values[target]=value
    def delete(self,target): self.values.pop(target,None)


def proposal(**changes):
    value={"summary":"隔离规划示例，不代表现场事实已确认", "fields":{"name":"FDC 创建夹具","scenario":"fdc","area":"FA","cpu":"Q26UDV","equipment":"LUL Conveyor","requirements":"测试一台搬送机马达负载上报；点表和验收值待工程师确认"},
           "questions":["请提供点表与验收指标"],"agent_ids":["cim-fdc","fa-glass"],"pack_ids":["fa-starter"]}
    return {**value,**changes}


@pytest.fixture
def configured(tmp_path):
    calls=[]
    def transport(settings,key,messages):
        calls.append({"settings":settings,"messages":messages})
        assert key=="synthetic-only-key"
        return json.dumps(proposal(),ensure_ascii=False)
    service=FactoryService(tmp_path/"business",planner_transport=transport,planner_secrets=Secrets())
    service.planner.save_settings({"api_key":"synthetic-only-key"})
    return service,calls


def draft(service,request_id="fixture-call-001",**changes):
    return service.planner.propose(request_id=request_id,brief="公开且无敏感信息的测试需求",input_classification="public",**changes)


def preview(service,d):
    fields={**d["proposal"]["fields"],"classification":"internal"}
    return service.planner.preview(fields,d["proposal"]["agent_ids"],d["proposal"]["pack_ids"])


def create(service,d,p):
    return service.planner.create(draft_id=d["id"],fields=p["fields"],agent_ids=d["proposal"]["agent_ids"],pack_ids=d["proposal"]["pack_ids"],fingerprint=p["fingerprint"])


def test_settings_never_publish_or_store_plaintext_keys_in_business_records(configured):
    service,_=configured
    settings=service.planner.settings()
    assert settings["has_key"] and settings["model"]=="deepseek-flash"
    assert "synthetic-only-key" not in json.dumps(settings)
    with service.connect() as db:
        assert "synthetic-only-key" not in "\n".join(db.iterdump())
    service.planner.save_settings({"clear_key":True})
    assert not service.planner.settings()["has_key"]


def test_changed_endpoint_does_not_reuse_official_key(configured):
    service,_=configured
    service.planner.save_settings({"provider":"compatible","base_url":"http://127.0.0.1:11434/v1","model":"fixture"})
    assert not service.planner.settings()["has_key"]
    with pytest.raises(PlannerError):
        service.planner.save_settings({"clear_key":"false"})
    with pytest.raises(PlannerError):
        service.planner.save_settings({"base_url":"https://user:secret@example.invalid"})


def test_external_api_classification_and_internal_attestation(configured):
    service,calls=configured
    for classification in ("pending","internal","restricted"):
        with pytest.raises(PolicyDenied):
            service.planner.propose(request_id="denied-"+classification,brief="不得发送",input_classification=classification)
    assert not calls
    with pytest.raises(PlannerError):
        service.planner.save_settings({"provider":"compatible","destination":"internal","internal_confirmed":True})
    with pytest.raises(PlannerError):
        service.planner.save_settings({"provider":"compatible","base_url":"http://127.0.0.1:11434/v1","destination":"internal","internal_confirmed":False})


def test_creation_model_receives_only_new_brief_and_catalog_not_existing_projects(configured):
    service,calls=configured
    service.create_project("existing-private-marker",classification="restricted",requirements="never-send-existing-requirements")
    d=draft(service)
    assert d["status"]=="completed" and len(calls)==1
    messages=json.dumps(calls[0]["messages"],ensure_ascii=False)
    assert "现状、目标、纳入/排除设备" in messages
    assert "公开且无敏感信息" in messages
    assert "existing-private-marker" not in messages and "never-send-existing-requirements" not in messages
    assert len(service.list_projects())==1 and d["created_project_id"] is None


def test_replay_and_concurrent_call_ids_do_not_issue_duplicate_model_requests(configured):
    service,calls=configured
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:draft(service),range(4)))
    assert len(calls)==1
    assert service.planner.draft("fixture-call-001")["status"]=="completed"
    assert all(r["id"]=="fixture-call-001" for r in results)
    assert draft(service)["status"]=="completed" and len(calls)==1
    with pytest.raises(Conflict):
        service.planner.propose(request_id="fixture-call-001",brief="不同内容",input_classification="public")


@pytest.mark.parametrize("raw",["", "not json", json.dumps(proposal(agent_ids=["invented-agent"])), json.dumps({**proposal(),"shell":"not-allowed"})])
def test_invalid_model_output_never_creates_project(configured,raw):
    service,_=configured
    service.planner.transport=lambda *_:raw
    d=draft(service)
    assert d["status"]=="failed" and not service.list_projects()


def test_unknown_facts_remain_null_and_preview_requires_explicit_inputs(configured):
    service,_=configured
    value=proposal()
    value["fields"].update(cpu=None,area=None,equipment=None)
    service.planner.transport=lambda *_:json.dumps(value)
    d=draft(service)
    assert d["proposal"]["fields"]["cpu"] is None
    with pytest.raises(PlannerError):
        service.planner.preview({k:v or "" for k,v in d["proposal"]["fields"].items()})


def test_followup_inherits_classification_and_records_cumulative_conversation(configured):
    service,calls=configured
    service.planner.save_settings({"provider":"compatible","base_url":"http://127.0.0.1:11434/v1","model":"fixture","destination":"internal","internal_confirmed":True,"api_key":"synthetic-only-key"})
    first=service.planner.propose(request_id="internal-first",brief="厂内待澄清需求",input_classification="restricted")
    second=service.planner.propose(request_id="internal-second",brief="补充 CPU 与范围",input_classification="public",parent_id=first["id"])
    assert second["input_classification"]=="restricted"
    assert len(calls[-1]["messages"])==4
    p=preview(service,second)
    with pytest.raises(PlannerError,match="分级"):
        create(service,second,p)
    service.planner.save_settings({"provider":"deepseek","base_url":"https://api.deepseek.com","destination":"external","internal_confirmed":False})
    with pytest.raises(PolicyDenied):
        service.planner.propose(request_id="external-followup",brief="继续",input_classification="public",parent_id=first["id"])


def test_configured_creation_is_atomic_idempotent_and_retains_review_gates(configured):
    service,calls=configured
    d=draft(service); p=preview(service,d)
    assert len(p["stages"])==7 and not p["automatic_execution"]
    assert p["skills"] and p["process_packs"][0]["status"]=="candidate"
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        projects=list(pool.map(lambda _:create(service,d,p),range(3)))
    assert len({p["id"] for p in projects})==1 and len(service.list_projects())==1
    details=service.detail(projects[0]["id"])
    assert not details["project"]["requirements_confirmed"]
    assert details["tasks"] and all(t["status"]=="queued" for t in details["tasks"])
    assert not details["attempts"] and not details["verification"] and len(calls)==1
    assert {"program-review","process-review","evidence-review"}<={t["agent_id"] for t in details["tasks"]}
    assert all(t["definition"]["process_packs"][0]["id"]=="fa-starter" for t in details["tasks"])
    baseline=next(t for t in details["tasks"] if t["stage"]=="baseline")
    with pytest.raises(Conflict):
        service.start_attempt(projects[0]["id"],baseline["id"],"baseline-cannot-start")


def test_stale_preview_or_failed_task_configuration_does_not_leave_partial_project(configured,monkeypatch):
    service,_=configured
    d=draft(service); p=preview(service,d)
    with pytest.raises(Conflict):
        service.planner.create(draft_id=d["id"],fields=p["fields"],agent_ids=d["proposal"]["agent_ids"],pack_ids=d["proposal"]["pack_ids"],fingerprint="stale")
    assert not service.list_projects()
    monkeypatch.setattr(service,"_plan_tasks",lambda *_: (_ for _ in ()).throw(RuntimeError("fixture rollback")))
    with pytest.raises(RuntimeError): create(service,d,p)
    assert not service.list_projects()
    assert service.planner.draft(d["id"])["created_project_id"] is None


def test_configuration_scope_change_falls_back_instead_of_reusing_wrong_cpu_agent(configured):
    service,_=configured
    d=draft(service); p=preview(service,d); created=create(service,d,p)
    service.update_project(created["id"],1,cpu="R04CPU")
    route=service.detail(created["id"])["route"]
    ids={a["agent"]["id"] for a in route["agents"]}
    assert "mitsubishi-r" in ids and "mitsubishi-q" not in ids
    assert not route["process_packs"] and any("配置已失效" in text for text in route["missing"])


def test_detailed_workflow_guide_has_real_handoffs_and_candidate_pack_limits(configured):
    service,_=configured
    guide=workflow_guide(service.registry,service.planner.definition)
    assert len(guide["stages"])==7 and len(guide["process_packs"])==4
    assert all(stage["operations"] and stage["inputs"] and stage["outputs"] and stage["completion"] and stage["rework"] for stage in guide["stages"])
    assert all(not pack["field_validated"] and pack["constraint_count"]==0 for pack in guide["process_packs"])


def test_planning_http_auth_csrf_validation_and_readonly(tmp_path):
    origin="http://127.0.0.1:8772"
    app=create_app(tmp_path/"engineering",origin=origin,operator_token="fixture-only")
    with TestClient(app,base_url=origin) as c:
        assert c.get("/api/cim/workflow-guide").status_code==401
        session=c.post("/api/session",json={"token":"fixture-only"}).json()
        assert c.get("/api/cim/workflow-guide").status_code==200
        assert c.post("/api/cim/planner/settings",json={"api_key":"never-store"}).status_code==403
        headers={"Origin":origin,"x-csrf-token":session["csrf"]}
        r=c.post("/api/cim/project-setup/preview",json={"fields":proposal()["fields"],"agent_ids":["not-a-real-agent"]},headers=headers)
        assert r.status_code==400
        r=c.post("/api/cim/project-drafts",json={"unknown":"field"},headers=headers)
        assert r.status_code==400


def test_sdk_request_uses_deepseek_chat_json_and_no_automatic_retry(monkeypatch):
    import httpx
    import openai
    from cim.planner import DEFAULT_SETTINGS,ProjectPlanner
    original=openai.OpenAI
    requests=[]
    def handler(request):
        requests.append(request)
        assert request.url=="https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"]=="Bearer synthetic-transport-key"
        body=json.loads(request.content)
        assert body["model"]=="deepseek-flash" and body["response_format"]=={"type":"json_object"}
        assert body["stream"] is False and body["max_tokens"]==6000
        return httpx.Response(200,json={"id":"fixture","object":"chat.completion","created":1,"model":"fixture",
            "choices":[{"index":0,"message":{"role":"assistant","content":"{}"},"finish_reason":"stop"}]})
    def client(**values):
        assert values["max_retries"]==0 and values["timeout"]==90
        return original(**values,http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(openai,"OpenAI",client)
    assert ProjectPlanner._complete(DEFAULT_SETTINGS,"synthetic-transport-key",[{"role":"user","content":"json fixture"}])=="{}"
    assert len(requests)==1


def test_provider_error_never_exposes_error_body_or_key(monkeypatch):
    import httpx
    import openai
    from cim.planner import DEFAULT_SETTINGS,ProjectPlanner
    original=openai.OpenAI
    def client(**values):
        return original(**values,http_client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(401,json={"error":{"message":"synthetic-key-must-not-leak"}}))))
    monkeypatch.setattr(openai,"OpenAI",client)
    with pytest.raises(PlannerError) as failure:
        ProjectPlanner._complete(DEFAULT_SETTINGS,"synthetic-key-must-not-leak",[{"role":"user","content":"json fixture"}])
    assert "鉴权失败" in str(failure.value) and "synthetic-key" not in str(failure.value)


def test_restart_marks_unfinished_call_uncertain_without_resubmitting(configured):
    service,calls=configured
    with service.connect(True) as db:
        service._put(db,"creation_draft",{"id":"fixture-interrupted","status":"running","run_id":"older-run","messages":[],"request_hash":"old"},"_planner")
    value=service.planner.draft("fixture-interrupted")
    assert value["status"]=="uncertain" and "未自动重发" in value["error"]
    assert not calls


def test_readonly_planning_interface_can_read_guide_but_not_store_config(tmp_path):
    origin="http://127.0.0.1:8772"
    app=create_app(tmp_path/"engineering",origin=origin,operator_token="fixture-only",read_only=True)
    with TestClient(app,base_url=origin) as c:
        session=c.post("/api/session",json={"token":"fixture-only"}).json()
        headers={"Origin":origin,"x-csrf-token":session["csrf"]}
        assert c.get("/api/cim/workflow-guide").status_code==200
        assert c.post("/api/cim/planner/settings",json={"api_key":"not-stored"},headers=headers).status_code==403
