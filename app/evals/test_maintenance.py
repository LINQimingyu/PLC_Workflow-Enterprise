"""QA-only capability lifecycle and execution-boundary regressions."""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from factory_enterprise.maintenance import Maintenance,builtin_id
from factory_enterprise.http import create_app
from factory_enterprise.operations import Operations
from test_enterprise import world,config,baseline,evidence

@pytest.fixture
def maint(world):
    s,o,e,r,p=world
    with s.db.tx(False) as c:first=c.execute('SELECT id FROM ep_users WHERE admin=true LIMIT 1').fetchone()['id']
    admin=s.auth.create_user(first,'maint_'+uuid4().hex[:10],'QA maintenance admin','QA-Maintenance-Password-2026',admin=True)
    with s.db.tx(False) as c:
        originals={kind:s.db.rows(c,kind) for kind in ['capability_binding','capability_control']}
    with s.db.tx() as c:
        for kind in originals:c.execute('DELETE FROM ep_records WHERE kind=%s',(kind,))
    try:
        yield Maintenance(s),admin,world
    finally:
        with s.db.tx() as c:
            for kind,rows in originals.items():
                c.execute('DELETE FROM ep_records WHERE kind=%s',(kind,))
                for row in rows:s.db.put(c,kind,row)

def draft(m,admin,kind='skill',module='control',key=None):
    return m.create(admin['id'],kind,key or 'qa-'+uuid4().hex[:10],'QA capability',[module],'QA only method',
                    implementation='control.dispatch' if kind=='tool' else '',note='QA only maintenance')

def published(m,admin,**kw):
    v=draft(m,admin,**kw);return m.publish(admin['id'],v['id'],v['sha256'],'QA only publication')

def bind_skill(m,admin,ident):
    with m.s.db.tx(False) as c:b=m.binding(c,'control')
    return m.bind(admin['id'],'control',b['agent_id'],ident,b['tool_ids'],b['revision'],'QA only binding')

def run(w,tools=None):
    s,o,e,r,p=w
    return s.create_run(o,p,'control','QA contract','QA only',[],['AnalysisDelivery'],['QA'],e,r,tools=tools or [])

def test_admin_only_and_http_csrf(maint):
    m,admin,(s,o,e,r,p)=maint
    with pytest.raises(PermissionError):m.listing(o)
    client=TestClient(create_app(s,'http://127.0.0.1:8774'),base_url='http://127.0.0.1:8774')
    assert client.get('/api/maintenance').status_code==401
    response=client.post('/api/session',json={'username':admin['username'],'password':'QA-Maintenance-Password-2026'},headers={'origin':'http://127.0.0.1:8774'})
    assert response.status_code==200
    assert client.get('/api/maintenance').status_code==200
    assert client.post('/api/maintenance/versions',json={}).status_code==403

def test_drafts_optimistic_edit_and_immutable_publication(maint):
    m,a,w=maint;v=draft(m,a)
    with pytest.raises(ValueError,match='变化'):m.edit(a['id'],v['id'],'stale','QA',["control"],'changed',note='QA')
    v=m.edit(a['id'],v['id'],v['sha256'],'QA revised',['control'],'changed QA method',note='QA')
    v=m.publish(a['id'],v['id'],v['sha256'],'QA')
    with pytest.raises(ValueError,match='不可改写'):m.edit(a['id'],v['id'],v['sha256'],'QA',['control'],'changed',note='QA')
    derived=m.create(a['id'],'skill',v['key'],'QA v2',['control'],'QA v2 method',base_id=v['id'],expected_sha=v['sha256'],note='QA revision')
    assert derived['version']==2 and derived['status']=='draft'
    assert len(m.read(a['id'],v['id'])['history'])==2

def test_binding_changes_new_contract_only_and_disabled_version_blocks(maint):
    m,a,w=maint;s,o,e,r,p=w
    first=published(m,a);bind_skill(m,a,first['id']);old=run(w)
    second=published(m,a);bind_skill(m,a,second['id']);new=run(w)
    assert old['contract']['skill']['version_id']==first['id']
    assert new['contract']['skill']['version_id']==second['id']
    assert s.detail(o,p)['run'][0]['contract_hash']==old['contract_hash']
    s.authorize_run(o,old['id']);s.authorize_run(o,new['id'])
    m.enable(a['id'],first['id'],False,'QA stop')
    with s.db.tx(False) as c:
        with pytest.raises(PermissionError,match='停用'):s._check_run(c,s.db.get(c,old['id'],'run'))
        s._check_run(c,s.db.get(c,new['id'],'run'))

def test_draft_wrong_module_and_stale_binding_are_rejected(maint):
    m,a,w=maint
    with pytest.raises(ValueError,match='未发布'):bind_skill(m,a,draft(m,a)['id'])
    with pytest.raises(ValueError,match='不匹配'):bind_skill(m,a,published(m,a,module='energy')['id'])
    with m.s.db.tx(False) as c:b=m.binding(c,'control')
    m.bind(a['id'],'control',b['agent_id'],b['skill_id'],[],b['revision'],'QA remove tools')
    with pytest.raises(ValueError,match='变化'):m.bind(a['id'],'control',b['agent_id'],b['skill_id'],[],b['revision'],'QA stale')

def test_tool_configuration_cannot_expand_executor_scope(maint):
    m,a,w=maint
    with pytest.raises(ValueError,match='已准入'):m.create(a['id'],'tool','qa-invalid','QA tool',['control'],'QA',implementation='shell.exec',note='QA')
    tool=published(m,a,kind='tool')
    with m.s.db.tx(False) as c:b=m.binding(c,'control')
    m.bind(a['id'],'control',b['agent_id'],b['skill_id'],[tool['id']],b['revision'],'QA tool binding')
    r=run(w,['control.dispatch']);assert tool['id'] in [v['id'] for v in r['contract']['capability_refs']]
    m.enable(a['id'],tool['id'],False,'QA stop tool')
    with pytest.raises(PermissionError,match='停用'):run(w,['control.dispatch'])

def test_capability_disable_rejects_late_effect_result(maint):
    m,a,w=maint;s,o,e,r,p=w
    v=published(m,a);bind_skill(m,a,v['id']);task=run(w);s.authorize_run(o,task['id'])
    ops=Operations(s);op,_=ops._claim(task['id'],'QA-effect','tool',{'tool':'QA only'})
    m.enable(a['id'],v['id'],False,'QA stop during effect')
    assert ops._finish(op,{'QA':'late'})['rejected']
    with s.db.tx(False) as c:assert s.db.get(c,op['id'],'operation')['status']=='late'

def test_builtin_disable_and_no_arbitrary_identity_creation(maint):
    m,a,w=maint;s,o,e,r,p=w
    ident=builtin_id('skill','control')
    m.enable(a['id'],ident,False,'QA emergency stop')
    try:
        with pytest.raises(ValueError,match='停用'):run(w)
    finally:m.enable(a['id'],ident,True,'QA restore baseline')
    assert all(x['status']=='published' for x in m.listing(a['id'])['items'] if x['builtin'])

def test_effective_catalog_uses_bound_versions_without_exposing_instructions(maint):
    m,a,w=maint;s,o,e,r,p=w
    v=published(m,a);bind_skill(m,a,v['id'])
    module=next(x for x in m.effective_catalog(o)['modules'] if x['id']=='control')
    assert module['skill_version']['id']==v['id'] and 'instructions' not in module['skill_version']
    m.enable(a['id'],builtin_id('tool','control.dispatch'),False,'QA stop tool')
    module=next(x for x in m.effective_catalog(o)['modules'] if x['id']=='control')
    assert 'control.dispatch' not in module['tools']

def test_disabling_accepted_module_dependency_blocks_engineering_gate(maint):
    m,a,w=maint;s,o,e,r,p=w
    v=published(m,a);bind_skill(m,a,v['id']);*_,code=baseline(w)
    task=run(w);s.authorize_run(o,task['id'])
    s.submit_run(e,task['id'],summary='QA candidate',deliverables=[{'type':'AnalysisDelivery','title':'QA only','payload':{'conclusion':'QA','limits':'QA synthetic'}}])
    s.review_run(r,task['id'],True,'QA independent review')
    for stage in ['static','compile','simulation']:evidence(w,code,stage)
    assert not s.detail(o,p)['gates']['engineering']['blockers']
    m.enable(a['id'],v['id'],False,'QA dependency stop')
    assert '模块依据能力版本已停用或失效' in s.detail(o,p)['gates']['engineering']['blockers']
