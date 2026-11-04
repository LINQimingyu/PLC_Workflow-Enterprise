from __future__ import annotations
from fastapi import Request
from fastapi import Query
from fastapi.responses import Response,JSONResponse
from .commands import invoke
from .records import Conflict
from .service import FactoryService
from .policy import PolicyDenied
from .planner import PlannerError
from .guide import workflow_guide


def register(app,engineering):
    service=FactoryService(engineering.projects.workspace.parent/"business",engineering=engineering,read_only=engineering.read_only)
    app.state.factory=service
    engineering.factory=service

    @app.exception_handler(PlannerError)
    async def planner_error(_request,error):
        return JSONResponse({"error":{"code":"cim_planner","message":str(error)}},status_code=400)

    def planner_command(call,data):
        import inspect
        engineering.writable()
        try:
            inspect.signature(call).bind(**data)
        except TypeError:
            raise PlannerError("规划请求字段与接口不匹配") from None
        try:
            return call(**data)
        except Conflict:
            raise
        except ValueError as error:
            raise PlannerError(str(error)) from None

    @app.get("/api/cim/workflow-guide")
    def guide():
        return workflow_guide(service.registry,service.planner.definition)

    @app.get("/api/cim/planner/settings")
    def planner_settings():
        return service.planner.settings()

    @app.post("/api/cim/planner/settings")
    def save_planner_settings(data:dict):
        engineering.writable()
        return service.planner.save_settings(data)

    @app.post("/api/cim/project-drafts")
    def propose(data:dict):
        return planner_command(service.planner.propose,data)

    @app.get("/api/cim/project-drafts/{draft_id}")
    def project_draft(draft_id:str):
        return service.planner.draft(draft_id)

    @app.post("/api/cim/project-setup/preview")
    def preview_setup(data:dict):
        return planner_command(service.planner.preview,data)

    @app.post("/api/cim/project-setup/create")
    def create_setup(data:dict):
        return planner_command(service.planner.create,data)

    @app.exception_handler(PolicyDenied)
    async def policy_denied(_request,error):
        return JSONResponse({"error":{"code":"cim_data_policy","message":str(error)}},status_code=403)

    @app.exception_handler(Conflict)
    async def conflict(_request,error):
        return JSONResponse({"error":{"code":"cim_conflict","message":str(error)}},status_code=409)

    @app.get("/api/cim/catalog")
    def catalog():
        r=service.registry
        return {"agents":list(r.agents.values()),"skills":list(r.skills.values()),"process_packs":list(r.packs.values()),
                "creation_agent":service.planner.definition,
                "execution_modes":["manual_internal","deterministic_tools"],"upstream":"c3a0f0b1acab12964ccb6004841c8de4b26ad1d2"}

    @app.get("/api/cim/projects")
    def projects():
        return {"projects":service.list_projects()}

    @app.post("/api/cim/projects",status_code=201)
    def create(data:dict):
        engineering.writable()
        return service.create_project(**data)

    @app.get("/api/cim/projects/{pid}")
    def detail(pid:str):
        return service.detail(pid)

    @app.get("/api/cim/projects/{pid}/workflow")
    def workflow(pid:str):
        return service.workflow(pid)

    @app.post("/api/cim/projects/{pid}/commands/{action}")
    def command(pid:str,action:str,data:dict):
        engineering.writable()
        try:
            return invoke(service,pid,action,data)
        except Conflict:
            raise
        except ValueError as error:
            return JSONResponse({"error":{"code":"cim_invalid_input","message":str(error)[:500]}},status_code=400)

    @app.get("/api/cim/projects/{pid}/search")
    def search(pid:str,q:str,include_shared:bool=False):
        return service.search(pid,q,include_shared=include_shared)

    @app.get("/api/cim/projects/{pid}/audit")
    def audit(pid:str,limit:int|None=Query(default=None,ge=1,le=100),before_seq:int|None=Query(default=None,ge=1)):
        if limit is None and before_seq is None:
            return {"events":service.audit(pid)}
        events=service.workflow_history(pid,limit=limit or 20,before_seq=before_seq)
        return {"events":events,"next_before_seq":events[-1]["seq"] if len(events)==(limit or 20) else None}

    @app.get("/api/cim/projects/{pid}/documents/{doc_id}")
    def document(pid:str,doc_id:str):
        meta,raw=service.read_document(pid,doc_id)
        return Response(raw,media_type="application/octet-stream",headers={"Content-Disposition":'attachment; filename="'+doc_id+'"'})

    @app.get("/api/cim/projects/{pid}/attempts/{attempt_id}/bundle")
    def bundle(pid:str,attempt_id:str,destination:str="internal"):
        return Response(service.bundle(pid,attempt_id,destination),media_type="application/zip",
                        headers={"Content-Disposition":'attachment; filename="task-'+attempt_id+'.zip"'})

    @app.get("/api/cim/projects/{pid}/archive-bundle")
    def archive_bundle(pid:str,destination:str="internal"):
        return Response(service.archive_bundle(pid,destination),media_type="application/zip",
                        headers={"Content-Disposition":'attachment; filename="archive-'+pid+'.zip"'})
