"""Acceptance against real PostgreSQL. QA fixtures never assert real GX/site success."""
import json,os
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from factory_enterprise.service import EnterpriseService
from factory_enterprise.operations import Operations,electrical,energy,diagnosis
from factory_enterprise.graph import EnterpriseGraph
from factory_enterprise.http import create_app
from factory_enterprise.catalog import catalog
ROOT=Path(__file__).resolve().parents[2]

@pytest.fixture(scope='session')
def config():
    path=Path(os.environ.get('EP_TEST_CONFIG',ROOT/'.qa/config.json')).resolve()
    if not path.is_relative_to(ROOT/'.qa'):raise RuntimeError('Tests require .qa config')
    if not path.exists():pytest.skip('Prepare PostgreSQL: deploy/local_postgres.py --qa')
    cfg=json.loads(path.read_text(encoding='utf-8'))
    if cfg['environment']!='qa' or 'plc_enterprise_qa' not in cfg['dsn']:raise RuntimeError('Refuse production DB')
    return cfg

@pytest.fixture
def world(config):
    s=EnterpriseService(config['dsn'],config['root'],'qa')
    key=uuid4().hex[:10];pw='TestOnly-Strong-Password-2026'
    with s.db.tx(False) as c:first=c.execute('SELECT id FROM ep_users WHERE admin=true LIMIT 1').fetchone()
    admin=first['id'] if first else s.auth.create_user(None,'admin_'+key,'测试管理员',pw,bootstrap=True)['id']
    o=s.auth.create_user(admin,'owner_'+key,'测试项目负责人',pw)['id']
    e=s.auth.create_user(admin,'engineer_'+key,'测试执行工程师',pw)['id']
    r=s.auth.create_user(admin,'reviewer_'+key,'测试独立审核人',pw)['id']
    p=s.create_project(o,'测试项目 '+key,'离线工程交付',['plc','diagnosis','electrical','improvement','energy'])['id']
    s.auth.members(o,p,e,['engineer','validator','knowledge','viewer'])
    s.auth.members(o,p,r,['reviewer','validator','knowledge','viewer'])
    return s,o,e,r,p

def art(s,u,p,t,payload,data=None,slot=None):return s.artifact(u,p,t,t,payload,data,slot)
def gate(s,u,p,g):
    st=s.detail(u,p)['gates'][g]
    return s.decide_gate(u,p,g,st['signature'],True,'QA审核，非真实工程验收')
def codepayload():return {'changes':'QA only','io':['X0'],'tests':['normal','failure','recovery'],'rollback':'original'}
def baseline(w):
    s,o,e,r,p=w
    original=art(s,e,p,'Original',{'source':'qa fixture','classification':'internal'},b'original QA bytes','source')
    profile={'device':'QA设备','cpu':'Q26UDV','firmware':'QA-fw','ide':'GX Works2','ide_version':'1.635','libraries':['QA-lib-v1'],
             'original_ids':[original['id']],'permissions':['offline_only']}
    art(s,e,p,'ToolchainProfile',profile)
    req=art(s,e,p,'RequirementSpec',{'goal':'离线候选','scope':'QA','exclusions':'无在线设备','acceptance':['QA'],'key_io':['X0'],'interlocks':['QA']})
    gate(s,o,p,'input')
    art(s,e,p,'EngineeringPlan',{'solution':'QA候选','validation':['static','compile','simulation'],'rollback':'原始版本','impact':'离线'})
    gate(s,o,p,'plan')
    code=art(s,e,p,'CodeBundle',codepayload(),b'QA-code-0')
    return original,profile,req,code
def evidence(w,candidate,stage='compile',outcome='passed',failure_kind='program',provenance='real'):
    s,o,e,r,p=w
    log=art(s,e,p,'Original',{'source':'QA imported log fixture; not a real GX record','classification':'internal','purpose':'evidence'},
            ('QA ONLY '+stage+outcome).encode(),'log-'+uuid4().hex)
    j=s.import_evidence(e,p,candidate['id'],stage,outcome,log['id'],['QA coverage'],provenance,failure_kind)
    return s.verify_evidence(r,j['id'],'QA verification only')
def make_run(w,mode='manual',module='plc'):
    s,o,e,r,p=w
    a=next(x for x in s.detail(o,p)['artifact'] if x['type']=='RequirementSpec' and x['active'])
    return s.create_run(o,p,module,'QA交付','仅QA',[a['id']],['AnalysisDelivery'],['QA检查'],e,r,mode,
                        tools=['plc.inspect_csv'] if module=='plc' else [])

def test_catalog_modules():
    c=catalog()
    assert {m['id'] for m in c['modules']}=={'control','plc','diagnosis','electrical','improvement','energy','review','validation','delivery','knowledge'}
    assert c['runtime']=='LangGraph' and c['database']=='PostgreSQL'

def test_identity_isolation(world):
    s,o,e,r,p=world
    with pytest.raises(PermissionError):s.projects('typed-name')
    other=s.create_project(e,'另一个项目','QA',['plc'])['id']
    with pytest.raises(PermissionError):s.detail(o,other)
    with pytest.raises(PermissionError):s.auth.members(e,p,r,['owner'])

def test_gate_missing_and_stale(world):
    s,o,e,r,p=world
    with pytest.raises(ValueError,match='缺少'):gate(s,o,p,'input')
    baseline(world);st=s.detail(o,p)['gates']['input'];assert st['approved']
    a=next(x for x in s.detail(o,p)['artifact'] if x['type']=='RequirementSpec' and x['active'])
    art(s,e,p,'RequirementSpec',{**a['payload'],'goal':'改变目标'})
    assert not s.detail(o,p)['gates']['input']['approved']
    with pytest.raises(ValueError,match='变化'):s.decide_gate(o,p,'input',st['signature'],True,'旧对象')

def test_release_and_tamper(world):
    s,o,e,r,p=world;*_,code=baseline(world)
    with pytest.raises(ValueError,match='真实'):gate(s,o,p,'engineering')
    for stage in ['static','compile','simulation']:evidence(world,code,stage)
    for g in ['engineering','risk','release']:gate(s,o,p,g)
    st=s.detail(o,p)['gates']['release'];release=s.release(o,p,st['signature'])
    assert s.export_release(o,release['id'])[:2]==b'PK'
    assert s.detail(o,p)['project']['lifecycle']=={'release':'released','implementation':'not_recorded','site':'not_recorded','benefit':'not_recorded'}
    (s.root/'blobs'/code['sha256'][:2]/code['sha256']).write_bytes(b'tampered')
    try:
        with pytest.raises(ValueError,match='摘要'):s.export_release(o,release['id'])
    finally:(s.root/'blobs'/code['sha256'][:2]/code['sha256']).write_bytes(b'QA-code-0')

def test_permission_revocation(world):
    s,o,e,r,p=world;baseline(world);run=make_run(world);s.authorize_run(o,run['id'])
    s.auth.members(o,p,e,[])
    assert s.submit_run(e,run['id'],'迟到候选',[])['rejected']
    assert not s.detail(o,p)['gates']['input']['approved']

def test_grant_revoke(world):
    s,o,e,r,p=world;baseline(world);run=make_run(world);g=s.authorize_run(o,run['id'])
    assert s.agent_identity(run['id'],g['agent_token'])=='agent:'+run['id']
    s.revoke_run(o,run['id'])
    assert s.submit_run(e,run['id'],'迟到结果',[])['rejected']

def test_separate_reviewer(world):
    s,o,e,r,p=world;baseline(world);run=make_run(world);s.authorize_run(o,run['id'])
    s.submit_run(e,run['id'],'候选',[{'type':'AnalysisDelivery','title':'分析','payload':{'conclusion':'QA','limits':'仅QA'}}])
    with pytest.raises(PermissionError):s.review_run(e,run['id'],True,'自审')
    assert s.review_run(r,run['id'],True,'独立审核')['status']=='accepted'

def test_graph_restart_and_repeat(world):
    s,o,e,r,p=world;baseline(world);run=make_run(world);s.authorize_run(o,run['id'])
    g=EnterpriseGraph(s,Operations(s));a=g.advance(o,p)
    assert any(x['kind']=='module_input' for x in a['waiting'])
    s.submit_run(e,run['id'],'QA候选',[{'type':'AnalysisDelivery','title':'QA','payload':{'conclusion':'QA','limits':'QA'}}])
    restarted=EnterpriseService(s.db.dsn,s.root,'qa');g=EnterpriseGraph(restarted,Operations(restarted))
    b=g.advance(r,p);assert any(x['kind']=='module_review' for x in b['waiting'])
    s.review_run(r,run['id'],True,'QA独立审核');g.advance(o,p);g.advance(o,p)
    assert len([x for x in s.detail(o,p)['artifact'] if x['type']=='AnalysisDelivery'])==1

def test_graph_revocation(world):
    s,o,e,r,p=world;baseline(world);run=make_run(world);s.authorize_run(o,run['id'])
    g=EnterpriseGraph(s,Operations(s));g.advance(o,p);s.revoke_run(o,run['id'])
    with pytest.raises((PermissionError,ValueError)):g.advance(o,p)

def test_unknown_no_retry(world):
    s,o,e,r,p=world;baseline(world);unbound=make_run(world,'api')
    with pytest.raises(ValueError,match='模型'):s.authorize_run(o,unbound['id'])
    s.revoke_run(o,unbound['id'])
    run=make_run(world,'bundle');s.authorize_run(o,run['id']);ops=Operations(s)
    op,execute=ops._claim(run['id'],'m0','model',{'synthetic':True});assert execute
    ops.recover_unknown()
    with pytest.raises(ValueError,match='不明'):ops._claim(run['id'],'m0','model',{'synthetic':True})
    ops.reconcile(o,op['id'],'已核查，不重试')
    with pytest.raises(ValueError):ops._claim(run['id'],'m0','model',{'synthetic':True})

def test_tool_receipt_budget(world):
    s,o,e,r,p=world;baseline(world)
    run=s.create_run(o,p,'electrical','QA计算','QA',[],['ElectricalDesignPackage'],['QA'],e,r,'manual',
                     tools=['electrical.calculate'],budget={'model_calls':0,'tool_calls':1,'tokens':0})
    s.authorize_run(o,run['id']);ops=Operations(s)
    args={'power_kw':10,'voltage_v':380,'power_factor':0.8,'efficiency':0.9,'phases':3}
    a=ops.tool(run['id'],'one','electrical.calculate',args);b=ops.tool(run['id'],'one','electrical.calculate',args)
    assert a==b and a['current_a']>0
    with pytest.raises(ValueError,match='预算'):ops.tool(run['id'],'two','electrical.calculate',args)

def test_concurrent_effect_once(world):
    s,o,e,r,p=world;baseline(world);run=make_run(world);s.authorize_run(o,run['id']);ops=Operations(s)
    def claim(_):
        try:return ops._claim(run['id'],'same','model',{})[1]
        except ValueError:return False
    with ThreadPoolExecutor(2) as pool:assert sum(pool.map(claim,range(2)))==1

def test_three_repairs_stop(world):
    s,o,e,r,p=world;*_,code=baseline(world);failure=evidence(world,code,outcome='failed')
    for n in range(3):
        patch=s.propose_patch(e,p,code['id'],failure['id'],'修复QA','回退QA',f'QA-code-{n+1}'.encode(),'candidate.gxw',codepayload())
        with pytest.raises(ValueError):s.apply_patch(e,patch['id'])
        s.approve_patch(r,patch['id'],patch['sha256'],'独立人工批准QA')
        applied=s.apply_patch(e,patch['id']);assert s.apply_patch(e,patch['id'])['candidate_id']==applied['candidate_id']
        code=next(x for x in s.detail(o,p)['artifact'] if x['id']==applied['candidate_id'])
        failure=evidence(world,code,outcome='failed')
    d=s.detail(o,p)
    assert d['project']['stopped'] and d['project']['failure_streak']==3
    with pytest.raises(ValueError,match='人工接管'):s.propose_patch(e,p,code['id'],failure['id'],'再修','回退',b'QA4','x.gxw',codepayload())
    assert s.take_over(o,p,'人工接管')['failure_streak']==0

def test_environment_separate(world):
    s,o,e,r,p=world;*_,code=baseline(world);failure=evidence(world,code,outcome='failed')
    patch=s.propose_patch(e,p,code['id'],failure['id'],'QA','QA',b'QA-patch','x.gxw',codepayload())
    s.approve_patch(r,patch['id'],patch['sha256'],'QA');patch=s.apply_patch(e,patch['id'])
    code=next(x for x in s.detail(o,p)['artifact'] if x['id']==patch['candidate_id'])
    evidence(world,code,outcome='unavailable',failure_kind='environment')
    d=s.detail(o,p)['project'];assert d['failure_streak']==0 and d['environment_failures']==1

def test_synthetic_not_success(world):
    *_,code=baseline(world)
    with pytest.raises(ValueError,match='合成'):evidence(world,code,provenance='synthetic')

def test_high_risk_no_waiver(world):
    s,o,e,r,p=world;original,*_=baseline(world)
    risk=s.risk(e,p,'high','QA高风险','整改','回退')
    with pytest.raises(PermissionError):s.dispose_risk(o,risk['id'],'waived','QA',[original['id']])
    with pytest.raises(PermissionError):s.dispose_risk(e,risk['id'],'closed','QA',[original['id']])
    assert s.dispose_risk(r,risk['id'],'closed','QA核验',[original['id']])['status']=='closed'

def test_production_knowledge(world):
    s,o,e,r,p=world;original,*_=baseline(world)
    k=s.knowledge(e,p,'QA生产知识','production',[original['id']],{'cpu':'Q26UDV'},'QA only')
    with pytest.raises(PermissionError):
        with s.db.tx(False) as c:s._use_knowledge(c,e,k['id'],p,True)
    regression=art(s,e,p,'Original',{'source':'QA regression fixture, not production','classification':'internal','purpose':'evidence'},b'QA regression log','regression-'+uuid4().hex)
    for action in ['redaction','domain_review','regression']:s.knowledge_review(r,k['id'],action,'QA证据',[regression['id']])
    s.knowledge_review(r,k['id'],'approve','QA一审')
    with pytest.raises(PermissionError):s.knowledge_review(r,k['id'],'approve','同一人')
    with pytest.raises(ValueError):s.knowledge_review(o,k['id'],'publish','未双审')
    s.knowledge_review(o,k['id'],'approve','QA二审');s.knowledge_review(o,k['id'],'publish','QA发布')
    assert k['id'] in [x['id'] for x in s.knowledge_list(e,p,True)]
    s.knowledge_review(o,k['id'],'withdraw','QA撤回')
    assert not s.knowledge_list(e,p,True)

def test_personal_not_production(world):
    s,o,e,r,p=world;original,*_=baseline(world)
    k=s.knowledge(e,p,'QA个人','personal',[original['id']],{'cpu':'Q26UDV'},'静态')
    s.knowledge_review(e,k['id'],'accept','本人接受')
    assert s.knowledge_list(e,p,False) and not s.knowledge_list(e,p,True)

@pytest.mark.parametrize('fn,args',[(electrical,{}),(energy,{'energy_kwh':20,'good_units':0}),(electrical,{'power_kw':float('nan')})])
def test_missing_calculation(fn,args):
    with pytest.raises(ValueError):fn(args)
def test_diagnosis_missing():assert diagnosis({'device':'QA'})['status']=='needs_info'

def test_http_security(world):
    s,o,e,r,p=world;origin='http://127.0.0.1:8774';client=TestClient(create_app(s,origin,'qa-token'),base_url=origin)
    assert client.get('/api/projects').status_code==401
    assert client.get('/api/health',headers={'host':'evil'}).status_code==403
    assert client.post('/api/session',json={},headers={'origin':'https://evil.test'}).status_code==403
    with s.db.tx(False) as c:username=c.execute('SELECT username FROM ep_users WHERE id=%s',(o,)).fetchone()['username']
    a=client.post('/api/session',json={'username':username,'password':'TestOnly-Strong-Password-2026'},headers={'origin':origin})
    assert a.status_code==200
    assert client.post('/api/projects/'+p+'/controller',json={'mode':'agent'},headers={'origin':origin}).status_code==403
    headers={'origin':origin,'x-csrf-token':a.json()['csrf']}
    assert client.post('/api/projects/'+p+'/controller',json={'mode':'agent','actor':r},headers=headers).status_code==409
    assert client.post('/api/projects/'+p+'/controller',json={'mode':'agent'},headers=headers).status_code==200

def test_analysis_without_compile(world):
    s,o,e,r,p=world
    with s.db.tx() as c:
        q=s.db.get(c,p,'project');q['delivery']='analysis';s.db.put(c,'project',q)
    baseline(world);art(s,e,p,'AnalysisDelivery',{'conclusion':'QA分析','limits':'无真实编译与现场证据'})
    gate(s,o,p,'engineering')
    assert not s.detail(o,p)['job']

def test_metric_baseline_first(world):
    s,o,e,r,p=world;original,*_=baseline(world)
    with pytest.raises(ValueError,match='基线'):s.metric(e,p,'周期','确认至交付',5,'小时','QA',[original['id']],'target')
    s.metric(e,p,'周期','确认至交付',10,'小时','QA人工',[original['id']])
    assert s.metric(o,p,'周期','确认至交付',8,'小时','QA目标',[original['id']],'target')['value']==8

def test_api_graph_tool_loop(world):
    s,o,e,r,p=world;baseline(world);ops=Operations(s)
    with s.db.tx(False) as c:admin=c.execute('SELECT id FROM ep_users WHERE admin=true LIMIT 1').fetchone()['id']
    cfg=ops.save_model(admin,'QA synthetic model','http://127.0.0.1:19999/v1','qa-only','QA injected transport; no network')
    ops.transport=lambda *args:{'text':'{"probe":"ok"}','usage':{'total_tokens':5}}
    ops.probe(admin,cfg['id'])
    run=s.create_run(o,p,'electrical','QA model tool loop','QA',[],['ElectricalDesignPackage'],['QA'],e,r,'api',tools=['electrical.calculate'])
    ops.bind_model(o,run['id'],cfg['id']);s.authorize_run(o,run['id']);calls=[]
    def reply(config,messages,max_tokens):
        calls.append(messages)
        result={'action':'tool','tool':'electrical.calculate','arguments':{'power_kw':10,'voltage_v':380,'power_factor':.85,'efficiency':.9,'phases':3}} if len(calls)==1 else {
          'action':'final','summary':'QA candidate, not engineering acceptance','deliverables':[{'type':'ElectricalDesignPackage','title':'QA design',
          'payload':{'parameters':{'power_kw':10},'calculations':['QA tool result'],'bom':['QA draft'],'drawing_draft':'QA draft','construction_impact':'not implemented'}}]}
        return {'text':json.dumps(result),'usage':{'total_tokens':25}}
    ops.transport=reply;g=EnterpriseGraph(s,ops)
    result=g.advance(o,p)
    assert any(w['kind']=='module_review' for w in result['waiting']) and len(calls)==2
    s.review_run(r,run['id'],True,'QA independent review')
    EnterpriseGraph(s,ops).advance(o,p)
    assert len(calls)==2

def test_vendor_separate_unavailable_and_no_repeat(world):
    from factory_enterprise.vendor import VendorTasks
    s,o,e,r,p=world;*_,code=baseline(world)
    run=s.create_run(o,p,'validation','QA vendor task','QA',[code['id']],['CompileResult'],['QA'],e,r,'manual',tools=['vendor.compile'])
    s.authorize_run(o,run['id']);v=VendorTasks(s)
    job=v.request(e,p,run['id'],code['id'],'compile',['QA'],'qa-key',None)
    assert v.request(e,p,run['id'],code['id'],'compile',['QA'],'qa-key',None)['id']==job['id']
    completed=v.execute(job['id'],adapter=lambda *args:{'status':'unavailable','raw_log':'QA ONLY missing GX','failure_kind':'environment'})
    assert completed['status']=='unavailable'
    with pytest.raises(ValueError):v.execute(job['id'])
    assert s.detail(o,p)['project']['environment_failures']==1

def test_agent_controller_cannot_self_review_or_bypass(world):
    s,o,e,r,p=world
    s.controller(o,p,'agent');baseline(world)
    target=s.create_run(o,p,'plc','QA target','QA',[],['AnalysisDelivery'],['QA'],e,r,'bundle',ordinary_review=True)
    controller=s.create_run(o,p,'control','QA supervisor','Only existing grants',[],['AnalysisDelivery'],['QA'],e,r,'bundle',tools=['control.dispatch','control.review'])
    s.authorize_run(o,target['id']);s.authorize_run(o,controller['id']);ops=Operations(s)
    assert ops.tool(controller['id'],'dispatch','control.dispatch',{'run_id':target['id']})['scope_unchanged']
    s.submit_run(e,target['id'],'QA target',[{'type':'AnalysisDelivery','title':'QA','payload':{'conclusion':'QA','limits':'QA'}}])
    ops.tool(controller['id'],'review','control.review',{'run_id':target['id'],'accepted':True,'note':'QA delegated ordinary review'})
    with pytest.raises(PermissionError):s.review_run('agent:'+controller['id'],controller['id'],True,'self')
    with pytest.raises(PermissionError):ops.tool(controller['id'],'shell','shell.exec',{})
    assert next(x for x in s.detail(o,p)['run'] if x['id']==target['id'])['review']['by']=='agent:'+controller['id']

def test_gate_withdrawal_stops_authorized_task(world):
    s,o,e,r,p=world;baseline(world);run=make_run(world);s.authorize_run(o,run['id'])
    st=s.detail(o,p)['gates']['input'];s.decide_gate(o,p,'input',st['signature'],False,'QA withdrawal')
    assert s.submit_run(e,run['id'],'late',[])['rejected']
    assert not s.detail(o,p)['gates']['plan']['approved']

def test_no_direct_repair_bypass(world):
    s,o,e,r,p=world;*_,code=baseline(world);evidence(world,code,outcome='failed')
    with pytest.raises(ValueError,match='补丁'):art(s,e,p,'CodeBundle',codepayload(),b'QA bypass')

def test_risk_artifact_creates_blocker(world):
    s,o,e,r,p=world;baseline(world)
    art(s,e,p,'RiskFinding',{'severity':'high','description':'QA hazard','mitigation':'QA fix','rollback':'QA revert'})
    assert s.detail(o,p)['risk'][0]['status']=='open'

def test_module_contract_not_rewritten_and_role_bound(world):
    s,o,e,r,p=world;baseline(world);run=make_run(world);original=run['contract_hash']
    s.authorize_run(o,run['id']);s.revoke_run(o,run['id'])
    assert next(x for x in s.detail(o,p)['run'] if x['id']==run['id'])['contract_hash']==original
    with pytest.raises(PermissionError):s.create_run(o,p,'energy','bad','bad',[],['CodeBundle'],['QA'],e,r)

def test_knowledge_withdrawal_blocks_release_and_completed_graph(world):
    s,o,e,r,p=world
    with s.db.tx() as c:
        project=s.db.get(c,p,'project');project['delivery']='analysis';s.db.put(c,'project',project)
    original,_,req,_=baseline(world)
    k=s.knowledge(e,p,'QA formal source','production',[original['id']],{'cpu':'Q26UDV'},'QA only')
    log=art(s,e,p,'Original',{'source':'QA regression log','classification':'internal','purpose':'evidence'},b'QA regression','QA-reg')
    for action in ['redaction','domain_review','regression']:s.knowledge_review(r,k['id'],action,'QA review',[log['id']])
    for person in [r,o]:s.knowledge_review(person,k['id'],'approve','QA distinct review')
    s.knowledge_review(o,k['id'],'publish','QA publish')
    run=s.create_run(o,p,'plc','QA knowledge use','QA',[req['id']],['AnalysisDelivery'],['QA'],e,r,knowledge_ids=[k['id']])
    s.authorize_run(o,run['id'])
    s.submit_run(e,run['id'],'QA analysis',[{'type':'AnalysisDelivery','title':'QA','payload':{'conclusion':'QA','limits':'QA'}}])
    s.review_run(r,run['id'],True,'QA reviewer')
    for g in ['engineering','risk','release']:gate(s,o,p,g)
    rel=s.release(o,p,s.detail(o,p)['gates']['release']['signature'])
    g=EnterpriseGraph(s,Operations(s));assert g.advance(o,p)['completed']
    affected=s.knowledge_review(o,k['id'],'withdraw','QA withdrawal')
    assert p in affected['affected_projects']
    with pytest.raises(ValueError):s.export_release(o,rel['id'])
    assert not g.advance(o,p)['completed']

def test_release_includes_historical_log_version(world):
    s,o,e,r,p=world;*_,code=baseline(world)
    jobs=[evidence(world,code,stage) for stage in ['static','compile','simulation']]
    first=jobs[0]
    log=next(a for a in s.detail(o,p)['artifact'] if a['id']==first['log_id'])
    art(s,e,p,'Original',log['payload'],b'QA newer log kept separately',log['slot'])
    for g in ['engineering','risk','release']:gate(s,o,p,g)
    rel=s.release(o,p,s.detail(o,p)['gates']['release']['signature'])
    refs=rel['manifest']['artifacts']
    assert any(a['id']==log['id'] and not a['current_at_release'] for a in refs)
    from zipfile import ZipFile
    from io import BytesIO
    with ZipFile(BytesIO(s.export_release(o,rel['id']))) as z:
        assert any(log['id'] in name for name in z.namelist())

def test_mcp_is_grant_bound(world):
    from factory_enterprise.mcp import ModuleTools,create_server
    s,o,e,r,p=world;original,*_=baseline(world);run=make_run(world);grant=s.authorize_run(o,run['id'])
    adapter=ModuleTools(s,run['id'],grant['agent_token'])
    assert adapter.call('module_read_contract',{})['module']=='plc'
    with pytest.raises(PermissionError):adapter.call('module_read_evidence',{'source_id':original['id']})
    with pytest.raises(PermissionError):adapter.call('approve_gate',{})
    assert create_server(adapter)
    s.revoke_run(o,run['id'])
    with pytest.raises(PermissionError):adapter.call('module_read_contract',{})
