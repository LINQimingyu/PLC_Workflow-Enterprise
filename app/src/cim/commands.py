"""Explicit command dispatch, shared by authenticated operator HTTP and CLI."""
from __future__ import annotations
import base64
import inspect
from . import tt
from .engineering import csv_compare, inspect_csv


def invoke(service,pid,action,data):
    methods={"update":service.update_project,"confirm":service.confirm_requirements,"plan":service.plan_tasks,
             "start":service.start_attempt,"submit":service.submit_result,"review":service.review_task,
             "status":service.project_status,"revoke":service.revoke_document,"link":service.link_engineering,
             "classify":service.classify_document,
             "estimate":service.save_estimate,"verify":service.verification,"archive":service.archive,
             "publish-case":service.publish_case}
    methods["withdraw-case"]=service.withdraw_case
    if action in methods:
        call=methods[action]
        # Reject extra/missing fields before running a mutation, without exposing internal paths.
        try:
            inspect.signature(call).bind(pid,**data)
        except TypeError as e:
            raise ValueError("任务字段与合同不匹配") from e
        return call(pid,**data)
    if action=="document":
        body=dict(data)
        try:
            raw=base64.b64decode(body.pop("data_base64"),validate=True)
        except (ValueError,KeyError) as e:
            raise ValueError("文件 base64 内容无效") from e
        return service.add_document(pid,raw=raw,**body)
    if action in {"tt-analyze","csv-compare","csv-inspect","simulate"}:
        body=dict(data)
        revision=body.pop("expected_revision")
        if action=="tt-analyze":
            source=body.pop("source_id")
            meta,raw=service.read_document(pid,source)
            body["synthetic"]=bool(meta.get("metadata",{}).get("synthetic") or body.get("synthetic",False))
            result=tt.analyze(raw,**body)
            sources=[source]
        elif action=="csv-compare":
            before=body.pop("before_id")
            after=body.pop("after_id")
            if body:
                raise ValueError("CSV 对照不支持额外字段")
            _,a=service.read_document(pid,before)
            _,b=service.read_document(pid,after)
            result=csv_compare(a,b)
            sources=[before,after]
        elif action=="csv-inspect":
            source=body.pop("source_id")
            comment=body.pop("comment_source_id",None)
            _,raw=service.read_document(pid,source)
            if comment:
                _,comment_raw=service.read_document(pid,comment)
                body["comment_raw"]=comment_raw
            result=inspect_csv(raw,**body)
            sources=[source]+([comment] if comment else [])
        else:
            sources=body.pop("source_ids")
            if not sources:
                raise ValueError("仿真须绑定实测基线资料；演示也须引用合成数据资料")
            analysis_id=body.pop("baseline_analysis_id",None)
            analyses=[a for a in service.detail(pid)["analyses"] if a["kind"]=="tt-analyze" and a["revision"]==revision
                      and a["result"].get("quality")=="passed" and {x["id"] for x in a["sources"]}==set(sources)
                      and (analysis_id is None or a["id"]==analysis_id)]
            if not analyses:
                raise ValueError("先对相同资料和输入版本完成 TT 日志核查，再运行仿真")
            baseline=max(analyses,key=lambda a:a["created_at"])
            if body.get("observed_completed") not in (None,baseline["result"]["completed"]):
                raise ValueError("填报完成数与绑定日志的末站统计不一致")
            if body["config"]["duration_seconds"]!=baseline["result"]["window"]["seconds"]:
                raise ValueError("模型统计时长必须与绑定日志窗口一致")
            body["observed_completed"]=baseline["result"]["completed"]
            result=tt.compare(**body)
            result["baseline_analysis_id"]=baseline["id"]
            result["synthetic"]=baseline["result"].get("synthetic",False)
            result["configuration"]={k:body[k] for k in ["config","scenario","observed_completed"]}
            result["configuration"]["tolerance"]=body.get("tolerance",.1)
        return service.save_analysis(pid,revision,action,result,sources)
    raise ValueError("未知工作流动作")
