"""Guide transport uses generic QA-only fixtures, never business project material."""
import hashlib,json
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from factory_enterprise.http import create_app
from test_enterprise import world,config

ORIGIN='http://127.0.0.1:8774'
@pytest.fixture
def guide_app(world):
    s,o,e,r,p=world
    root=Path(__file__).resolve().parents[2]/'.qa'/('guide-'+uuid4().hex);root.mkdir()
    files={name:b'<!doctype html><html><script>window.qaFixture=true;</script><h1>QA ONLY GENERIC GUIDE</h1></html>' for name in ['index.html','architecture.html','workflow.html','architecture-note.html','workflow-note.html']}
    for name,data in files.items():(root/name).write_bytes(data)
    (root/'guide-manifest.json').write_text(json.dumps({'schema':'local-guide-1','files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}}),encoding='utf-8')
    return TestClient(create_app(s,ORIGIN,guide_root=root),base_url=ORIGIN),world,root

def login(client,s,ident,password='TestOnly-Strong-Password-2026'):
    with s.db.tx(False) as c:username=c.execute('SELECT username FROM ep_users WHERE id=%s',(ident,)).fetchone()['username']
    assert client.post('/api/session',json={'username':username,'password':password},headers={'origin':ORIGIN}).status_code==200

def test_guides_require_session_and_preserve_host_origin(guide_app):
    client,w,root=guide_app
    assert client.get('/api/guides/index').status_code==401
    assert client.get('/api/guides/architecture',headers={'host':'evil'}).status_code==403
    assert client.get('/api/guides/index',headers={'origin':'https://evil.test'}).status_code==403

def test_generic_guides_have_no_case_routes(guide_app):
    client,(s,o,e,r,p),root=guide_app;login(client,s,o)
    entries=client.get('/api/guides').json()
    assert [x['id'] for x in entries]==['architecture','workflow']
    assert all(x['available'] and x['allowed'] for x in entries)
    assert client.get('/api/guides/architecture').status_code==200
    for ident in ['case','case-note','case-template','case-source','not-an-allowed-file','guide-manifest.json']:
        assert client.get('/api/guides/'+ident).status_code==404

def test_guide_csp_is_digest_bound_and_api_policy_unchanged(guide_app):
    client,(s,o,e,r,p),root=guide_app;login(client,s,o)
    response=client.get('/api/guides/index');assert response.status_code==200
    policy=response.headers['content-security-policy']
    script=next(x for x in policy.split(';') if 'script-src' in x)
    assert 'sha256-' in script and 'unsafe-inline' not in script and 'unsafe-eval' not in script
    assert response.headers['cache-control']=='no-store'
    normal=client.get('/api/projects').headers['content-security-policy']
    assert 'sha256-' not in normal and "frame-ancestors 'none'" in normal

def test_modified_guide_is_not_executed(guide_app):
    client,(s,o,e,r,p),root=guide_app;login(client,s,o)
    (root/'index.html').write_bytes(b'<script>unapproved()</script>')
    assert client.get('/api/guides/index').status_code==409
