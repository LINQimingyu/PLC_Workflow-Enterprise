"""Independent enterprise HTTP surface; legacy token routes are not exposed here."""
import base64
import inspect
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit,quote
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from .catalog import catalog, digest
from .operations import Operations
from .graph import EnterpriseGraph
from .vendor import VendorTasks

def create_app(service,origin,setup_token='',static_dir=None,guide_root=None):
    parsed=urlsplit(origin)
    if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost','::1'} or parsed.path not in {'','/'}:
        raise ValueError('首期要求明确的本机 HTTP Origin')
    app=FastAPI(title='工厂电气工程企业平台',docs_url=None,redoc_url=None,openapi_url=None)
    ops=Operations(service);graph=EnterpriseGraph(service,ops)
    app.state.service=service;app.state.operations=ops;app.state.graph=graph
    failures=[]

    @app.exception_handler(PermissionError)
    async def permission(_request,error):return JSONResponse({'error':str(error)},status_code=403)
    @app.exception_handler(ValueError)
    async def invalid(_request,error):return JSONResponse({'error':str(error)},status_code=409)
    @app.exception_handler(KeyError)
    async def missing(_request,_error):return JSONResponse({'error':'记录不存在'},status_code=404)
    @app.exception_handler(Exception)
    async def unexpected(_request,_error):return JSONResponse({'error':'操作未完成，请检查企业服务日志'},status_code=500)

    @app.middleware('http')
    async def security(request,call_next):
        def deny(message,code=403):return JSONResponse({'error':message},status_code=code)
        if request.headers.get('host')!=parsed.netloc:return deny('不受信任的 Host')
        if request.headers.get('origin') not in {None,origin} or request.headers.get('sec-fetch-site')=='cross-site':return deny('不受信任的 Origin')
        if request.method=='OPTIONS':return deny('跨域访问未开放')
        path=request.url.path
        if request.method not in {'GET','HEAD'} and request.headers.get('origin')!=origin:return deny('缺少同源保护')
        if request.method in {'POST','PUT','PATCH'}:
            try:
                if int(request.headers.get('content-length','0'))>34*1024*1024:return deny('请求过大',413)
            except ValueError:return deny('请求长度无效',413)
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>34*1024*1024:return deny('请求过大',413)
            request._body=bytes(body)
        if path.startswith('/api/') and path not in {'/api/health','/api/setup','/api/session'}:
            try:user=service.auth.session(request.cookies.get('ep_session',''))
            except PermissionError:return deny('请登录',401)
            request.state.user=user
            if request.method not in {'GET','HEAD'} and not secrets.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):return deny('CSRF 校验失败')
        response=await call_next(request)
        response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'no-store' if path.startswith('/api/') else 'no-cache'})
        response.headers.setdefault('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        return response

    def actor(request):return request.state.user['id']
    async def invoke(request,call,*args,**extra):
        data=await request.json()
        if not isinstance(data,dict) or 'actor' in data:raise ValueError('身份由服务端会话确定')
        data.update(extra)
        if 'data_base64' in data:data['data']=base64.b64decode(data.pop('data_base64'),validate=True)
        try:inspect.signature(call).bind(*args,**data)
        except TypeError:raise ValueError('请求字段不符合业务接口') from None
        return await run_in_threadpool(call,*args,**data)

    @app.get('/api/health')
    def health():
        try:
            with service.db.tx(False) as c:c.execute('SELECT 1')
        except Exception:return JSONResponse({'status':'database_unavailable'},status_code=503)
        return {'status':'ok','runtime':'LangGraph','database':'PostgreSQL','environment':service.environment}
    @app.get('/api/setup')
    def setup_status():
        with service.db.tx(False) as c:needed=c.execute('SELECT count(*) AS n FROM ep_users').fetchone()['n']==0
        return {'required':needed}
    @app.post('/api/setup')
    async def setup(request:Request):
        body=await request.json()
        if not setup_token or not secrets.compare_digest(body.pop('token',''),setup_token):raise PermissionError('首次设置凭证无效，请使用本机设置链接')
        return service.auth.create_user(None,body['username'],body['display_name'],body['password'],bootstrap=True)
    @app.post('/api/session')
    async def login(request:Request):
        nonlocal failures
        failures=[t for t in failures if t>time.monotonic()-60]
        if len(failures)>=10:return JSONResponse({'error':'登录尝试过多，请稍后重试'},status_code=429)
        data=await request.json()
        try:token,csrf,user=service.auth.login(data['username'],data['password'])
        except PermissionError:
            failures.append(time.monotonic());raise
        response=JSONResponse({'user':user,'csrf':csrf});response.set_cookie('ep_session',token,httponly=True,samesite='strict',max_age=8*3600,path='/')
        return response
    @app.get('/api/session')
    def session(request:Request):
        try:return {'user':service.auth.session(request.cookies.get('ep_session',''))}
        except PermissionError:return JSONResponse({'error':'请登录'},status_code=401)
    @app.delete('/api/session')
    def logout(request:Request):
        u=service.auth.session(request.cookies.get('ep_session',''))
        if not secrets.compare_digest(request.headers.get('x-csrf-token',''),u['csrf']):raise PermissionError('CSRF 校验失败')
        with service.db.tx() as c:c.execute('DELETE FROM ep_sessions WHERE token_hash=%s',(digest(request.cookies.get('ep_session','').encode()),))
        response=JSONResponse({'ok':True});response.delete_cookie('ep_session');return response
    from .maintenance import Maintenance
    maintenance=Maintenance(service)
    @app.get('/api/maintenance')
    def maintenance_list(request:Request):return maintenance.listing(actor(request))
    @app.get('/api/maintenance/versions/{ident}')
    def maintenance_read(ident:str,request:Request):return maintenance.read(actor(request),ident)
    @app.post('/api/maintenance/versions')
    async def maintenance_create(request:Request):return await invoke(request,maintenance.create,actor(request))
    @app.post('/api/maintenance/versions/{ident}/edit')
    async def maintenance_edit(ident:str,request:Request):return await invoke(request,maintenance.edit,actor(request),ident)
    @app.post('/api/maintenance/versions/{ident}/publish')
    async def maintenance_publish(ident:str,request:Request):return await invoke(request,maintenance.publish,actor(request),ident)
    @app.post('/api/maintenance/versions/{ident}/enable')
    async def maintenance_enable(ident:str,request:Request):return await invoke(request,maintenance.enable,actor(request),ident)
    @app.post('/api/maintenance/bindings/{module}')
    async def maintenance_bind(module:str,request:Request):return await invoke(request,maintenance.bind,actor(request),module)
    @app.get('/api/catalog')
    def definitions(request:Request):return maintenance.effective_catalog(actor(request))
    @app.get('/api/users')
    def users(request:Request):
        with service.db.tx(False) as c:
            if not service.auth.user(c,actor(request))['admin']:raise PermissionError('需管理员')
            return c.execute('SELECT id,username,display_name,admin,enabled FROM ep_users ORDER BY username').fetchall()
    @app.post('/api/users')
    async def add_user(request:Request):return await invoke(request,service.auth.create_user,actor(request))
    @app.get('/api/projects')
    def projects(request:Request):return service.projects(actor(request))
    @app.post('/api/projects')
    async def project_create(request:Request):return await invoke(request,service.create_project,actor(request))
    @app.get('/api/projects/{project}')
    def project_detail(project:str,request:Request):return service.detail(actor(request),project)
    @app.post('/api/projects/{project}/controller')
    async def controller(project:str,request:Request):return await invoke(request,service.controller,actor(request),project)
    @app.post('/api/projects/{project}/members')
    async def member(project:str,request:Request):return await invoke(request,service.auth.members,actor(request),project)
    @app.post('/api/projects/{project}/artifacts')
    async def artifact(project:str,request:Request):return await invoke(request,service.artifact,actor(request),project)
    @app.get('/api/artifacts/{ident}/file')
    def download(ident:str,request:Request):
        a,data=service.read_artifact(actor(request),ident)
        return Response(data,media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename=\"artifact.bin\"; filename*=UTF-8''"+quote(a['filename'],safe='')})
    @app.post('/api/projects/{project}/gates')
    async def decide(project:str,request:Request):return await invoke(request,service.decide_gate,actor(request),project)
    @app.post('/api/projects/{project}/runs')
    async def create_run(project:str,request:Request):return await invoke(request,service.create_run,actor(request),project)
    @app.post('/api/module-runs/{ident}/{action}')
    async def run_action(ident:str,action:str,request:Request):
        calls={'authorize':service.authorize_run,'revoke':service.revoke_run,'renew':service.renew_run,'submit':service.submit_run,'review':service.review_run,'model':ops.bind_model}
        if action not in calls:raise ValueError('未知模块动作')
        return await invoke(request,calls[action],actor(request),ident)
    @app.get('/api/module-runs/{ident}/bundle')
    def bundle(ident:str,request:Request):return Response(service.contract_bundle(actor(request),ident),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="internal-task.zip"'})
    @app.post('/api/projects/{project}/graph')
    def advance(project:str,request:Request):return graph.advance(actor(request),project)
    @app.post('/api/projects/{project}/graph-reset')
    async def reset(project:str,request:Request):return await invoke(request,service.reset_flow,actor(request),project)
    @app.post('/api/projects/{project}/tool-jobs')
    async def evidence(project:str,request:Request):return await invoke(request,service.import_evidence,actor(request),project)
    @app.post('/api/projects/{project}/vendor-jobs')
    async def vendor_job(project:str,request:Request):return await invoke(request,VendorTasks(service).request,actor(request),project)
    @app.post('/api/tool-jobs/{ident}/verify')
    async def verify(ident:str,request:Request):return await invoke(request,service.verify_evidence,actor(request),ident)
    @app.post('/api/tool-jobs/{ident}/reconcile')
    async def reconcile_vendor(ident:str,request:Request):return await invoke(request,VendorTasks(service).reconcile,actor(request),ident)
    @app.post('/api/projects/{project}/patches')
    async def patch(project:str,request:Request):return await invoke(request,service.propose_patch,actor(request),project)
    @app.post('/api/patches/{ident}/{action}')
    async def patch_action(ident:str,action:str,request:Request):
        calls={'approve':service.approve_patch,'apply':service.apply_patch}
        if action not in calls:raise ValueError('未知补丁动作')
        return await invoke(request,calls[action],actor(request),ident)
    @app.post('/api/projects/{project}/takeover')
    async def takeover(project:str,request:Request):return await invoke(request,service.take_over,actor(request),project)
    @app.post('/api/projects/{project}/risks')
    async def risk(project:str,request:Request):return await invoke(request,service.risk,actor(request),project)
    @app.post('/api/risks/{ident}')
    async def dispose(ident:str,request:Request):return await invoke(request,service.dispose_risk,actor(request),ident)
    @app.post('/api/projects/{project}/releases')
    async def release(project:str,request:Request):return await invoke(request,service.release,actor(request),project)
    @app.get('/api/releases/{ident}/export')
    def export(ident:str,request:Request):return Response(service.export_release(actor(request),ident),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="engineering-release.zip"'})
    @app.post('/api/projects/{project}/lifecycle')
    async def lifecycle(project:str,request:Request):return await invoke(request,service.lifecycle,actor(request),project)
    @app.post('/api/projects/{project}/knowledge')
    async def knowledge(project:str,request:Request):return await invoke(request,service.knowledge,actor(request),project)
    @app.get('/api/projects/{project}/knowledge')
    def knowledge_list(project:str,request:Request,formal:bool=False):return service.knowledge_list(actor(request),project,formal)
    @app.get('/api/projects/{project}/knowledge-search')
    def knowledge_search(project:str,request:Request,q:str,formal:bool=True):return service.search_knowledge(actor(request),project,q,formal)
    @app.post('/api/knowledge/{ident}')
    async def knowledge_review(ident:str,request:Request):return await invoke(request,service.knowledge_review,actor(request),ident)
    @app.post('/api/projects/{project}/metrics')
    async def metric(project:str,request:Request):return await invoke(request,service.metric,actor(request),project)
    @app.post('/api/projects/{project}/legacy-mappings')
    async def legacy(project:str,request:Request):return await invoke(request,service.legacy_mapping,actor(request),project)
    @app.post('/api/projects/{project}/components')
    async def component(project:str,request:Request):return await invoke(request,service.component,actor(request),project)
    @app.get('/api/models')
    def models(request:Request):
        with service.db.tx(False) as c:
            service.auth.user(c,actor(request));return service.db.rows(c,'model')
    @app.post('/api/models')
    async def model(request:Request):return await invoke(request,ops.save_model,actor(request))
    @app.post('/api/models/{ident}/probe')
    async def probe(ident:str,request:Request):return await invoke(request,ops.probe,actor(request),ident)
    @app.post('/api/operations/{ident}/reconcile')
    async def reconcile(ident:str,request:Request):return await invoke(request,ops.reconcile,actor(request),ident)
    @app.post('/api/module-runs/{ident}/tools')
    async def tool(ident:str,request:Request):
        with service.db.tx(False) as c:
            r=service.db.get(c,ident,'run');service._p(c,actor(request),r['project_id'],{'engineer','validator','owner'})
            if actor(request)!=r['contract']['executor']:raise PermissionError('需合同指定执行者')
        return await invoke(request,ops.tool,ident)
    from .guides import register_guides
    register_guides(app,guide_root)
    if static_dir and Path(static_dir).is_dir():app.mount('/',StaticFiles(directory=static_dir,html=True),name='enterprise')
    return app
