import json
from pathlib import Path
import pytest
from cim.registry import Registry


@pytest.fixture
def registry():
    return Registry()


def test_catalog_has_traceable_contracts_and_real_skill_entrypoints(registry):
    assert len(registry.agents)==34
    assert len(registry.skills)==41
    for a in registry.agents.values():
        assert a["inputs"] and a["outputs"] and a["responsibility"]
        assert a["field_validated"] is False and a["status"]=="candidate"
        s=registry.snapshot(a["id"])
        assert all("---\nname:" in k["instructions"] for k in s["skills"])
        assert len(s["sha256"])==64
        assert {"knowledge.search","evidence.read"}<=set(a["tools"])
        assert not any("native" in t or "write_plc" in t for t in a["tools"])


@pytest.mark.parametrize("area,equipment,expected",[
    ("ARRAY","湿制程清洗机","array-wet"),("ARRAY","真空腔体","array-vacuum"),
    ("ARRAY","黄光曝光","array-photo"),("CF","涂布烘烤","cf-coat-bake"),
    ("CF","曝光显影","cf-photo"),("CELL","成盒贴合","cell-bond"),
    ("CELL","切割研磨","cell-cut"),("CELL","检测","cell-inspection"),
    ("FA","LUL Conveyor","fa-glass"),("FA","仓储供料","fa-storage"),
    ("CF","LUL 搬送","fa-glass")])
def test_equipment_routes_to_matching_expert(registry,area,equipment,expected):
    route=registry.route({"scenario":"fdc","area":area,"cpu":"Q26UDV","equipment":equipment})
    ids={x["agent"]["id"] for x in route["agents"]}
    assert expected in ids
    assert "mitsubishi-q" in ids and "mitsubishi-r" not in ids
    assert "cell-bond" not in ids or area=="CELL"


def test_unknown_equipment_does_not_invent_specialist_and_r_stays_unverified(registry):
    r=registry.route({"scenario":"tt","area":"CF","cpu":"R04CPU","equipment":""})
    assert r["missing"] and any("未验证" in x for x in r["missing"])
    assert not any(x["agent"]["category"]=="process" for x in r["agents"])
    assert "q-source" not in {s["id"] for a in r["agents"] for s in a["skills"]}


def test_empty_process_packs_never_claim_confirmed_factory_rules(registry):
    for p in registry.packs.values():
        assert p["unknowns"] and not p["confirmed_facts"] and not p["field_validated"]
