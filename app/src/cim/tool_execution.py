"""Attempt-bound, idempotent deterministic tools. Never launches a model or PLC."""
from .commands import invoke
from .records import Conflict,now,uid
from .registry import digest

TOOLS={"plc.inspect_csv":"csv-inspect","plc.compare_csv":"csv-compare","tt.analyze":"tt-analyze",
       "tt.simulate":"simulate","business.estimate":"estimate"}


def execute(service,pid,attempt_id,tool,arguments,request_id):
    if tool not in TOOLS or not isinstance(arguments,dict) or not isinstance(request_id,str) or not 8<=len(request_id)<=100:
        raise ValueError("工具或幂等请求字段无效")
    command_hash=digest({"attempt_id":attempt_id,"tool":tool,"arguments":arguments})
    with service.connect(True) as db:
        p=service._project(db,pid)
        a=service._get(db,"attempt",attempt_id)
        if a["project_id"]!=pid:
            raise PermissionError("批次不属于项目")
        t=service._get(db,"task",a["task_id"])
        for old in service._list(db,"tool_call",pid):
            if old["request_id"]==request_id:
                if old["command_hash"]!=command_hash:
                    raise Conflict("工具幂等键已绑定其他参数")
                if old["status"]=="completed":
                    return old["receipt"]
                raise Conflict("工具批次未明确完成，需人工检查；不自动重复执行")
        service._assert_ready(db,t,p)
        if t["current_attempt"]!=attempt_id or t["status"]!="waiting_return" or tool not in a["contract"]["tools"]:
            raise PermissionError("本批次未开放该工具")
        allowed={d["id"] for d in a["contract"]["input_snapshot"]["sources"]}
        refs=set(arguments.get("source_ids",[]))
        refs.update(arguments[k] for k in ["source_id","before_id","after_id","comment_source_id"] if arguments.get(k))
        if not refs<=allowed:
            raise PermissionError("工具资料超出本批次输入快照")
        revision=a["contract"]["input_revision"]
        record={"id":uid(),"project_id":pid,"attempt_id":attempt_id,"tool":tool,"request_id":request_id,
                "command_hash":command_hash,"status":"running","created_at":now()}
        service._put(db,"tool_call",record)
        service._audit(db,pid,"tool.started",{"id":record["id"],"tool":tool})
    try:
        result=invoke(service,pid,TOOLS[tool],{**arguments,"expected_revision":revision})
        receipt={"record_id":result["id"],"kind":"estimate" if tool=="business.estimate" else "analysis",
                 "revision":result["revision"],"field_verified":False}
        with service.connect(True) as db:
            record.update(status="completed",receipt=receipt,completed_at=now())
            service._put(db,"tool_call",record)
            service._audit(db,pid,"tool.completed",{"id":record["id"],"record_id":result["id"]})
        return receipt
    except Exception:
        with service.connect(True) as db:
            record.update(status="failed",completed_at=now())
            service._put(db,"tool_call",record)
            service._audit(db,pid,"tool.failed",{"id":record["id"]})
        raise
