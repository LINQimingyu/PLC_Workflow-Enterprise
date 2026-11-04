"""Operator HTTP facade; upstream session/Host/Origin/CSRF middleware is retained."""
import base64
import inspect
from fastapi.responses import JSONResponse,Response
from jsonschema.exceptions import ValidationError
from cim.records import Conflict
from .service import FactoryService
from .catalog import catalog,template
from cim.registry import digest
from .operations import tool,health,backup

def register(app,engineering):
    service=FactoryService(engineering.projects.workspace.parent/"business-v3",engineering=engineering,read_only=engineering.read_only)
    app.state.factory_v3=service; engineering.factory_v3=service
    @app.exception_handler(ValidationError)
    async def invalid_result(request,error): return JSONResponse({"error":{"message":"回传结构不符合模块合同"}},status_code=400)
    @app.exception_handler(Conflict)
    async def conflict(request,error): return JSONResponse({"error":{"message":str(error)[:500]}},status_code=409)
    def command(fn,data,*args):
        engineering.writable()
        try: inspect.signature(fn).bind(*args,**data)
        except TypeError: return JSONResponse({"error":{"message":"请求字段与合同不匹配"}},status_code=400)
        return fn(*args,**data)
    @app.get('/api/v3/catalog')
    def capabilities(): return catalog()
    @app.get('/api/v3/readiness')
    def ready(): return health(service)
    @app.get('/api/v3/projects')
    def projects(): return {"projects":service.list_projects()}
    @app.post('/api/v3/projects')
    def create(data:dict):
        body=dict(data); fingerprint=body.pop('preview_hash',None)
        if fingerprint!=digest(body): raise ValueError('请先预览当前项目模块路线')
        return command(service.create_project,body)
    @app.post('/api/v3/plan-preview')
    def preview(data:dict):
        return {'preview_hash':digest(data),'modules':template(data.get('scenarios',[]),data.get('implementation',False),data.get('electrical',False))}
    @app.get('/api/v3/projects/{pid}')
    def detail(pid:str): return service.detail(pid)
    @app.post('/api/v3/projects/{pid}/commands/{action}')
    def mutate(pid:str,action:str,data:dict):
        methods={"configure":service.configure_module,"controller":service.controller_mode,"grant":service.grant,"start":service.start,"submit":service.submit,
                 "gate":service.gate,"accept-knowledge":service.accept_knowledge,"revoke-grant":service.revoke_grant,"cancel":service.cancel_run,
                 "update":service.update_project,"status":service.project_status,"revoke-document":service.revoke_document,"classify":service.classify_document,
                 "verify":service.verification,"link":service.link_engineering,"preview-outbound":service.runtime.preview_outbound,"approve-outbound":service.runtime.approve_outbound}
        if action=="document":
            body=dict(data); raw=base64.b64decode(body.pop("data_base64"),validate=True)
            return command(service.add_document,{**body,"raw":raw},pid)
        if action=="tool": return command(tool,data,service,pid)
        if action not in methods: raise ValueError("未知命令")
        return command(methods[action],data,pid)
    @app.get('/api/v3/projects/{pid}/runs/{rid}/bundle')
    def bundle(pid:str,rid:str): return Response(service.bundle(pid,rid),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="module-{rid}.zip"'})
    @app.get('/api/v3/projects/{pid}/documents/{did}')
    def document(pid:str,did:str):
        meta,raw=service.read_document(pid,did)
        return Response(raw,media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="{did}"'})
    @app.get('/api/v3/projects/{pid}/search')
    def search(pid:str,q:str): return service.knowledge.search(pid,q)
    @app.get('/api/v3/projects/{pid}/audit')
    def audit(pid:str): return {"events":service.audit(pid)}
    @app.get('/api/v3/connections')
    def connections():
        with service.connect() as db: return {"connections":service._list(db,"connection")}
    @app.post('/api/v3/connections')
    def save_connection(data:dict): return command(service.runtime.save_connection,data)
    @app.post('/api/v3/connections/{cid}/probe')
    def probe(cid:str): engineering.writable(); return service.runtime.probe(cid)
    @app.get('/api/v3/embedding')
    def embedding(): return service.knowledge.embedding_settings()
    @app.post('/api/v3/embedding')
    def configure_embedding(data:dict): return command(service.knowledge.configure,data)
    @app.post('/api/v3/reindex')
    def reindex(): engineering.writable(); return service.knowledge.reindex()
    @app.post('/api/v3/knowledge/{kid}/withdraw')
    def withdraw(kid:str,data:dict): return command(service.knowledge.withdraw,data,kid)
    @app.get('/api/v3/projects/{pid}/knowledge-options')
    def knowledge_options(pid:str):
        with service.connect() as db:
            p=service._project(db,pid); options=[]
            for k in service._list(db,'knowledge'):
                try:
                    item=service.knowledge.usable(db,k['id'],p)
                    options.append({key:item[key] for key in ['id','title','classification','index_status']})
                except (PermissionError,Conflict): continue
            return {'options':options}
    @app.post('/api/v3/backup')
    def save_backup(): engineering.writable(); return backup(service)
