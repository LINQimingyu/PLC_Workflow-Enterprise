import json
import pytest
from cim.service import FactoryService,Conflict
from cim.mcp import FactoryTools
from test_workflow import returned
from test_tt import raw,log_rows


def test_attempt_scoped_mcp_tools_are_idempotent_and_cannot_expand_input_or_permissions(tmp_path):
    s=FactoryService(tmp_path/"business")
    p=s.create_project("Tool execution",scenario="tt",classification="internal",requirements="离线 TT 工具测试",equipment="Conveyor")
    pid=p["id"]
    d=s.add_document(pid,1,"events.csv",raw(log_rows()),classification="internal",metadata={"synthetic":True})
    s.confirm_requirements(pid,2,"需求人")
    tasks=s.plan_tasks(pid,2)
    for task in [t for t in tasks if t["stage"] in {"requirements","baseline"}]:
        a=s.start_attempt(pid,task["id"],"prerequisite-"+task["id"])
        s.submit_result(pid,returned(a))
        s.review_task(pid,task["id"],"approve","评审人","仅离线测试")
    target=next(t for t in tasks if t["agent_id"]=="tt-capacity")
    a=s.start_attempt(pid,target["id"],"tt-tool-attempt-001")
    adapter=FactoryTools(s,pid,trusted_internal=True)
    args={"attempt_id":a["id"],"tool":"tt.analyze","arguments":{"source_id":d["id"],"terminal_station":"S2"},"request_id":"tt-run-once-001"}
    receipt=json.loads(adapter.call("factory_run_tool",args)["json_chunk"])
    duplicate=json.loads(adapter.call("factory_run_tool",args)["json_chunk"])
    assert receipt==duplicate and len(s.detail(pid)["analyses"])==1
    report=json.loads(adapter.call("factory_read_analysis",{"record_id":receipt["record_id"]})["json_chunk"])
    assert report["result"]["synthetic"] and report["result"]["bottleneck_candidate"]=="S2"
    with pytest.raises(Conflict):
        adapter.call("factory_run_tool",{**args,"arguments":{"source_id":d["id"],"terminal_station":"WRONG"}})
    with pytest.raises(PermissionError):
        adapter.call("factory_run_tool",{**args,"tool":"plc.inspect_csv","request_id":"not-allowed-001"})
    new=s.add_document(pid,2,"new-candidate.csv",raw(log_rows()),classification="internal",kind="candidate")
    with pytest.raises(PermissionError):
        adapter.call("factory_run_tool",{**args,"arguments":{"source_id":new["id"],"terminal_station":"S2"},"request_id":"out-of-scope-001"})
    external=FactoryTools(s,pid)
    with pytest.raises(PermissionError):
        external.call("factory_run_tool",args)
