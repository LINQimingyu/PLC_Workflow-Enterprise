import json
import time
import pytest
from factory_v3.service import FactoryService
from factory_v3.catalog import SPECS
from factory_v3.mcp import ModuleTools
from test_v3_modules import project,finish,baseline

@pytest.fixture
def s(tmp_path): return FactoryService(tmp_path/'business')

@pytest.mark.parametrize('scenario',['fdc','tt','process_optimization','retrofit'])
@pytest.mark.parametrize('change',['scope','pause','revoke','expiry','cross_project','wrong_hash','path','invalid_verdict'])
def test_live_contract_boundary_matrix(s,scenario,change):
    p=project(s,scenarios=[scenario]); m=s.detail(p['id'])['modules'][0]
    g=s.grant(p['id'],m['id'],actor='合成验收员'); r=s.start(p['id'],g['id'],'request-'+g['id'])
    result={'summary':'合成候选','verdict':'candidate','citations':[],'questions':[],'findings':[],'artifacts':[]}
    if change=='scope': s.update_project(p['id'],1,requirements='新范围')
    elif change=='pause': s.project_status(p['id'],'paused')
    elif change=='revoke': s.revoke_grant(p['id'],g['id'],'撤回')
    elif change=='expiry':
        with s.connect(True) as db: g['expires']=time.time()-1; s._put(db,'grant',g)
    elif change=='cross_project':
        q=project(s)
        with pytest.raises(PermissionError): s.submit(q['id'],r['id'],r['contract_hash'],result)
        return
    elif change=='wrong_hash':
        with pytest.raises(Exception): s.submit(p['id'],r['id'],'incorrect',result)
        return
    elif change=='path':
        result['artifacts']=[{'name':'C:\\private.txt','content':'bad'}]
        with pytest.raises(ValueError): s.submit(p['id'],r['id'],r['contract_hash'],result)
        return
    elif change=='invalid_verdict':
        result['verdict']='passed'
        with pytest.raises(Exception): s.submit(p['id'],r['id'],r['contract_hash'],result)
        return
    assert s.submit(p['id'],r['id'],r['contract_hash'],result)['stale']

@pytest.mark.parametrize('name',list(SPECS))
@pytest.mark.parametrize('forbidden',['shell.execute','plc.write_online','files.read_any'])
def test_no_module_defines_destructive_tools(name,forbidden):
    from factory_v3.catalog import definition
    d=definition(name,'Q26UDV','LUL','FA')
    assert forbidden not in d['agent']['tools']
    assert d['sha256'] and d['skills']

def connection(s,monkeypatch,destination='internal'):
    monkeypatch.setattr(s.runtime,'_endpoint',lambda c:['127.0.0.1'])
    c=s.runtime.save_connection(name='合成模型',base_url='http://127.0.0.1:19999' if destination=='internal' else 'https://example.invalid',model='synthetic-fixture',destination=destination,deployment_evidence='仅合成传输测试，无实际模型')
    s.runtime.transport=lambda c,m,n:{'text':'{"probe":"ok"}','usage':None,'model':'synthetic-fixture'}
    s.runtime.probe(c['id']);return c

def test_api_executes_candidate_never_auto_accepts(s,monkeypatch):
    c=connection(s,monkeypatch);p=project(s);m=s.detail(p['id'])['modules'][0]
    s.runtime.transport=lambda c,m,n:{'text':json.dumps({'summary':'合成 API 交付','verdict':'candidate','citations':[],'questions':[],'findings':[],'artifacts':[]}), 'usage':{'total_tokens':100},'model':'fixture'}
    g=s.grant(p['id'],m['id'],mode='api',connection_id=c['id'],actor='人'); s.start(p['id'],g['id'],'request-001')
    assert s.runtime.tick()
    assert s.detail(p['id'])['modules'][0]['status']=='review'

def test_external_api_without_outbound_approval_makes_no_call(s,monkeypatch):
    c=connection(s,monkeypatch,'external');p=project(s);m=s.detail(p['id'])['modules'][0];calls=[]
    s.runtime.transport=lambda *args:calls.append(args)
    g=s.grant(p['id'],m['id'],mode='api',connection_id=c['id'],actor='人');s.start(p['id'],g['id'],'request-001');s.runtime.tick()
    assert not calls and s.detail(p['id'])['runs'][0]['status']=='blocked'

def test_api_error_is_unknown_without_retry(s,monkeypatch):
    c=connection(s,monkeypatch);p=project(s);m=s.detail(p['id'])['modules'][0];calls=[]
    def fail(*args): calls.append(1); raise TimeoutError()
    s.runtime.transport=fail
    g=s.grant(p['id'],m['id'],mode='api',connection_id=c['id'],actor='人');s.start(p['id'],g['id'],'request-001');s.runtime.tick();s.runtime.tick()
    assert len(calls)==1 and s.detail(p['id'])['runs'][0]['status']=='unknown'

def test_mcp_has_no_human_gate_or_cross_source_access(s):
    p=project(s); m=s.detail(p['id'])['modules'][0];g=s.grant(p['id'],m['id'],actor='人');r=s.start(p['id'],g['id'],'request-001')
    adapter=ModuleTools(s,p['id'],g['id'],r['id'],True)
    with pytest.raises(PermissionError): adapter.call('human_gate',{})
    with pytest.raises(PermissionError): adapter.call('module_read_evidence',{'source_id':'outside'})
    assert adapter.call('module_read_contract',{})['json_chunk']

def test_human_gate_after_execution_grant_expiry(s):
    p=project(s);m=s.detail(p['id'])['modules'][0];g=s.grant(p['id'],m['id'],actor='人');r=s.start(p['id'],g['id'],'request-001')
    result={'summary':'交付','verdict':'candidate','citations':[],'questions':[],'findings':[],'artifacts':[]}
    d=s.submit(p['id'],r['id'],r['contract_hash'],result)
    with s.connect(True) as db:g['expires']=time.time()-1;s._put(db,'grant',g)
    assert s.gate(p['id'],m['id'],d['id'],d['result_hash'],'accept','人','人工核对')['subject']=='human'

def test_internal_agent_tool_loop_is_bounded_and_receipted(s,monkeypatch):
    c=connection(s,monkeypatch);p=project(s);m=s.detail(p['id'])['modules'][0]
    responses=[{'action':'tool','tool':'business.estimate','arguments':{'data':{'bom':[],'labor':{},'daily_rate':None,'benefit':{'kind':'nonmonetary','basis':'合成测试无货币收益'},'assumptions':[]}}},
               {'summary':'合成工具回执已核对，成本仍有未知项','verdict':'candidate','citations':[],'questions':[],'findings':[],'artifacts':[]}]
    s.runtime.transport=lambda *args:{'text':json.dumps(responses.pop(0)), 'usage':None,'model':'fixture'}
    g=s.grant(p['id'],m['id'],mode='api',connection_id=c['id'],actor='人',max_tokens=128000);s.start(p['id'],g['id'],'request-001');s.runtime.tick()
    d=s.detail(p['id'])
    assert d['modules'][0]['status']=='review'
    assert len(d['operations'])==1 and d['operations'][0]['status']=='completed'
    assert d['grants'][0]['calls']==2 and d['grants'][0]['tool_calls']==1

def test_ai_gate_does_not_publish_cross_project_knowledge(s,monkeypatch):
    c=connection(s,monkeypatch);p=project(s,controller='agent');baseline(s,p)
    m=next(m for m in s.detail(p['id'])['modules'] if m['key']=='cim')
    m=s.configure_module(p['id'],m['id'],m['version'],review_mode='agent')
    g=s.grant(p['id'],m['id'],actor='人');r=s.start(p['id'],g['id'],'request-001')
    s.submit(p['id'],r['id'],r['contract_hash'],{'summary':'合成 CIM 交付','verdict':'candidate','citations':[],'questions':[],'findings':[],'artifacts':[]})
    before=len(s.detail(p['id'])['knowledges'])
    s.runtime.transport=lambda *args:{'text':json.dumps({'decision':'accept','note':'合成总控审核，无现场结论'}),'usage':None,'model':'fixture'}
    rg=s.grant(p['id'],m['id'],mode='api',purpose='review',connection_id=c['id'],actor='人');s.start(p['id'],rg['id'],'review-001');s.runtime.tick()
    d=s.detail(p['id'])
    assert next(x for x in d['modules'] if x['key']=='cim')['status']=='accepted'
    assert len(d['knowledges'])==before
    assert d['gates'][-1]['subject']=='agent'

def test_api_queued_run_cannot_be_started_twice(s,monkeypatch):
    c=connection(s,monkeypatch);p=project(s);m=s.detail(p['id'])['modules'][0]
    g=s.grant(p['id'],m['id'],mode='api',connection_id=c['id'],actor='人');s.start(p['id'],g['id'],'request-001')
    with pytest.raises(Exception): s.start(p['id'],g['id'],'request-002')

def test_knowledge_provenance_tracks_inherited_originals(s):
    p=project(s);doc=baseline(s,p);finish(s,p,'cim')
    entries=[k for k in s.detail(p['id'])['knowledges'] if k['module_id']==next(m['id'] for m in s.detail(p['id'])['modules'] if m['key']=='cim')]
    assert doc['id'] in {d['id'] for d in entries[0]['sources']}
    q=project(s)
    with s.connect() as db: assert s.knowledge.usable(db,entries[0]['id'],q)
    s.revoke_document(p['id'],doc['id'],s.detail(p['id'])['project']['revision'],'合成撤回')
    with s.connect() as db:
        with pytest.raises(PermissionError): s.knowledge.usable(db,entries[0]['id'],q)
