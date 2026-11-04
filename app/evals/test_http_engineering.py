import base64
import hashlib
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from integrations.web.app import create_app
from cim.workbench import FactoryWorkbench
from cim.engineering import csv_compare,inspect_csv
from cim.mcp import FactoryTools,create_server
from cim.service import FactoryService

ORIGIN="http://127.0.0.1:8772"


def test_http_uses_upstream_auth_csrf_and_shared_commands(tmp_path):
    workspace=tmp_path/"engineering"
    app=create_app(workspace,origin=ORIGIN,operator_token="test-only")
    with TestClient(app,base_url=ORIGIN) as c:
        assert c.get("/api/cim/projects").status_code==401
        assert c.get("/api/health").status_code==200
        s=c.post("/api/session",json={"token":"test-only"}).json()
        assert c.post("/api/cim/projects",json={"name":"No CSRF"}).status_code==403
        headers={"Origin":ORIGIN,"x-csrf-token":s["csrf"]}
        p=c.post("/api/cim/projects",json={"name":"HTTP Case","classification":"internal"},headers=headers).json()
        assert p["revision"]==1
        route=f"/api/cim/projects/{p['id']}/commands/"
        d=c.post(route+"document",json={"expected_revision":1,"name":"需求.md","data_base64":base64.b64encode("马达负载".encode()).decode(),"classification":"internal"},headers=headers)
        assert d.status_code==200
        assert c.get(f"/api/cim/projects/{p['id']}/search",params={"q":"马达负载"}).json()["citations"]
        assert c.post(route+"plan",json={"expected_revision":1},headers=headers).status_code==409
        assert c.post(route+"confirm",json={"expected_revision":2,"actor":"工程师"},headers=headers).status_code==400
        assert c.get("/api/cim/catalog",headers={"Origin":"https://untrusted.invalid"}).status_code==403
        assert len(c.get("/api/cim/catalog").json()["agents"])==34


def test_readonly_http_cannot_create_business_project(tmp_path):
    app=create_app(tmp_path/"engineering",origin=ORIGIN,operator_token="test-only",read_only=True)
    with TestClient(app,base_url=ORIGIN) as c:
        s=c.post("/api/session",json={"token":"test-only"}).json()
        r=c.post("/api/cim/projects",json={"name":"denied"},headers={"Origin":ORIGIN,"x-csrf-token":s["csrf"]})
        assert r.status_code==403


def test_factory_workbench_does_not_send_unclassified_engineering_to_model(tmp_path):
    service=FactoryWorkbench(tmp_path/"engineering",tmp_path/"state")
    app=create_app(tmp_path/"engineering",service=service,origin=ORIGIN,operator_token="test-only")
    with pytest.raises(PermissionError):
        service.submit({"project_id":"unknown-engineering"})


def test_real_historical_csvs_remain_byte_identical_and_comparison_is_static():
    root=Path(__file__).resolve().parents[3]/"项目案例"/"马达负载上报FDC开发"
    before=root/"001input/PHL 8线/8#CV4_7_CONV_4.csv"
    after=root/"002output/PHL08线/8#CV4_7_CONV_4_改造后.csv"
    if not before.is_file():
        pytest.skip("现场案例未随源码分发")
    a,b=before.read_bytes(),after.read_bytes()
    result=csv_compare(a,b)
    assert result["record_counts"]==[6262,6522] and result["format_valid"]==[True,True]
    assert result["non_step_change_blocks"] and not result["compile_verified"] and not result["field_verified"]
    assert before.read_bytes()==a and after.read_bytes()==b
    assert result["sha256_before"]==hashlib.sha256(a).hexdigest()


def test_csv_inspection_requires_no_invented_device_comment():
    root=Path(__file__).resolve().parents[3]/"项目案例"/"马达负载上报FDC开发"
    path=root/"001input/PHL 8线/8#CV4_7_CONV_4.csv"
    if not path.is_file(): pytest.skip("历史案例不可用")
    result=inspect_csv(path.read_bytes())
    assert not result["factory_notes"]["device_comments_provided"]
    assert result["coverage"] and result["factory_notes"]["warning"]


def test_mcp_v2_server_constructs_with_no_native_privileges(tmp_path):
    service=FactoryService(tmp_path/"business")
    p=service.create_project("MCP Case",classification="internal")
    assert create_server(FactoryTools(service,p["id"],trusted_internal=True)) is not None
