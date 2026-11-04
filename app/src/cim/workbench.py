"""Factory deployment guard around the upstream model job boundary."""
from application.workbench import WorkbenchService
from . import policy


class FactoryWorkbench(WorkbenchService):
    def _external_model_allowed(self,engineering_id):
        factory=getattr(self,"factory",None)
        if factory is None:
            raise PermissionError("厂内资料策略尚未初始化")
        linked=[]
        with factory.connect() as db:
            for p in factory._list(db,"project"):
                if any(b["project_id"]==engineering_id for b in p["engineering"]):
                    linked.append(p)
            if not linked:
                raise PermissionError("工程尚未关联已分级业务项目；使用厂内任务包分析")
            levels=[]
            for p in linked:
                levels.append(p["classification"])
                levels.extend(d["classification"] for d in factory._list(db,"document",p["id"]) if not d["revoked"])
            policy.allow(policy.inherited(*levels),"external")

    def submit(self,command):
        # First release executes internal AI via bundles. Only explicitly public
        # linked engineering data may use the upstream configurable model API.
        self._external_model_allowed(command["project_id"])
        return super().submit(command)

    def repair_generation(self,job_id,request_id):
        job=self.jobs.record(job_id)
        self._external_model_allowed(job["snapshot"]["project_id"])
        return super().repair_generation(job_id,request_id)
