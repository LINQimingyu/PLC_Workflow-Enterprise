import json
import pytest
from factory_v3.service import FactoryService
from factory_v3.catalog import catalog,template
from factory_v3.operations import backup,restore_check

@pytest.fixture
def s(tmp_path): return FactoryService(tmp_path/'workspace'/'business-v3')

def project(s,**kw):
    return s.create_project('合成验收',cpu='Q26UDV',equipment='LUL',classification='public',requirements='只读诊断；不实施；交付分析',**kw)

def finish(s,p,key,decision='accept',findings=None):
    m=next(m for m in s.detail(p['id'])['modules'] if m['key']==key)
    g=s.grant(p['id'],m['id'],actor='验收操作员')
    r=s.start(p['id'],g['id'],'request-'+g['id'])
    result={'summary':key+' 合成交付','verdict':'candidate','citations':[], 'findings':findings or [],'questions':[],'artifacts':[]}
    if g['contract']['sources']:
        d=g['contract']['sources'][0]
        result['citations']=[{'source_id':d['id'],'sha256':d['sha256'],'location':d['chunks'][0]['location']}]
    d=s.submit(p['id'],r['id'],r['contract_hash'],result)
    gate=s.gate(p['id'],m['id'],d['id'],d['result_hash'],decision,'验收操作员','合成流程检查')
    return m,g,r,d,gate

def baseline(s,p):
    finish(s,p,'scope')
    d=s.add_document(p['id'],1,'input.txt','合成设备点表：D100 负载，单位 %。'.encode(),classification='public')
    m=next(m for m in s.detail(p['id'])['modules'] if m['key']=='baseline')
    s.configure_module(p['id'],m['id'],m['version'],source_ids=[d['id']])
    finish(s,p,'baseline')
    return d

def test_templates_are_minimal_dags_and_cim_name():
    assert len(catalog()['agents'])==8
    assert next(a for a in catalog()['agents'] if a['id']=='cim')['name']=='CIM'
    for scenario in catalog()['scenarios']:
        rows=template([scenario]); seen=set()
        for m in rows:
            assert set(m['dependencies'])<=seen
            seen.add(m['key'])
        assert 'implementation' not in seen and 'electrical' not in seen

def test_end_to_end_manual_and_human_knowledge(s):
    p=project(s); baseline(s,p)
    for key in ['cim','proposal','review','verification','archive']: finish(s,p,key)
    assert s.detail(p['id'])['project']['status']=='archived'
    assert s.knowledge.search(p['id'],'合成交付')['hits']

def test_dependency_gate_and_critical_human(s):
    p=project(s,controller='agent'); m=s.detail(p['id'])['modules'][1]
    with pytest.raises(Exception): s.grant(p['id'],m['id'],actor='人')
    with pytest.raises(PermissionError): s.configure_module(p['id'],m['id'],1,review_mode='agent')

def test_revoked_grant_late_result_is_history(s):
    p=project(s); m=s.detail(p['id'])['modules'][0]; g=s.grant(p['id'],m['id'],actor='人'); r=s.start(p['id'],g['id'],'request-001')
    s.revoke_grant(p['id'],g['id'],'撤回')
    result={'summary':'迟到','verdict':'candidate','citations':[],'questions':[],'findings':[],'artifacts':[]}
    d=s.submit(p['id'],r['id'],r['contract_hash'],result)
    assert d['stale']
    with pytest.raises(Exception): s.gate(p['id'],m['id'],d['id'],d['result_hash'],'accept','人','意见')

def test_outbound_requires_public_and_specific_approval(s):
    p=project(s); m=s.detail(p['id'])['modules'][0]; g=s.grant(p['id'],m['id'],mode='bundle',actor='人')
    o=s.runtime.preview_outbound(p['id'],g['id']); r=s.start(p['id'],g['id'],'request-001')
    with pytest.raises(PermissionError): s.bundle(p['id'],r['id'])
    s.runtime.approve_outbound(p['id'],o['id'],o['fingerprint'],'人')
    assert s.bundle(p['id'],r['id']).startswith(b'PK')
    q=s.create_project('厂内',cpu='Q26UDV',equipment='LUL',classification='internal',requirements='内部')
    g=s.grant(q['id'],s.detail(q['id'])['modules'][0]['id'],actor='人')
    with pytest.raises(PermissionError): s.runtime.preview_outbound(q['id'],g['id'])

def test_cross_project_result_and_path_are_rejected(s):
    p=project(s); q=project(s); m=s.detail(p['id'])['modules'][0]; g=s.grant(p['id'],m['id'],actor='人'); r=s.start(p['id'],g['id'],'request-001')
    result={'summary':'x','verdict':'candidate','citations':[],'questions':[],'findings':[],'artifacts':[{'name':'../evil','content':'bad'}]}
    with pytest.raises(ValueError): s.submit(p['id'],r['id'],r['contract_hash'],result)
    result['artifacts']=[]
    with pytest.raises(PermissionError): s.submit(q['id'],r['id'],r['contract_hash'],result)

def test_partial_invalidation_and_withdrawal(s):
    p=project(s,scenarios=['fdc','tt']); doc=baseline(s,p)
    for key in ['cim','efficiency']: finish(s,p,key)
    detail=s.detail(p['id']); m=next(m for m in detail['modules'] if m['key']=='cim')
    s.configure_module(p['id'],m['id'],m['version'],source_ids=[doc['id']])
    states={m['key']:m['status'] for m in s.detail(p['id'])['modules']}
    assert states['efficiency']=='accepted' and states['cim']=='queued' and states['scope']=='accepted'

def test_backup_restore_does_not_run_models(s,tmp_path):
    project(s); b=backup(s)
    source=s.root.parent/'backups'/(b['id']+'.sqlite3')
    assert restore_check(source,tmp_path/'restored')['model_requests_sent']==0

def test_worker_unknown_not_automatically_retried(s):
    with s.connect(True) as db:
        s._put(db,'run',{'id':'r','project_id':'p','status':'running','fence':1})
    s.runtime.start_worker(); s.runtime.close()
    with s.connect() as db: assert s._get(db,'run','r')['status']=='unknown'
