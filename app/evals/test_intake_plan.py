"""Intake planning must neither satisfy nor obstruct engineering acceptance."""
import pytest
from factory_enterprise.catalog import digest
from test_enterprise import world,config,art,baseline,evidence,gate

def test_intake_does_not_replace_analysis_delivery(world):
    s,o,e,r,p=world
    art(s,o,p,'IntakePlan',{'scope':'QA only','tasks':'collect QA inputs','missing':'QA inputs'})
    baseline(world)
    with s.db.tx() as c:
        project=s.db.get(c,p,'project');project['delivery']='analysis';s.db.put(c,'project',project)
    assert '缺少分析交付与局限说明' in s.detail(o,p)['gates']['engineering']['blockers']

def test_intake_before_baseline_does_not_block_real_validation_rules(world):
    s,o,e,r,p=world
    art(s,o,p,'IntakePlan',{'scope':'QA only','tasks':'collect QA inputs','missing':'QA inputs'})
    *_,code=baseline(world)
    with pytest.raises(ValueError,match='真实'):gate(s,o,p,'engineering')
    for stage in ['static','compile','simulation']:evidence(world,code,stage)
    gate(s,o,p,'engineering')

def test_legacy_intake_is_reference_only_and_formal_analysis_stays_strict(world):
    s,o,e,r,p=world
    old=art(s,o,p,'AnalysisDelivery',{'conclusion':'QA old intake','limits':'QA missing'},slot='qa-legacy-fixture')
    # Emulate the previously stored schema in QA only; never rewrite production history.
    with s.db.tx() as c:
        old['slot']='project-intake';old['record_hash']=digest({k:v for k,v in old.items() if k not in {'active','record_hash'}});s.db.put(c,'artifact',old)
    *_,code=baseline(world)
    for stage in ['static','compile','simulation']:evidence(world,code,stage)
    assert not s.detail(o,p)['gates']['engineering']['blockers']
    with s.db.tx() as c:
        project=s.db.get(c,p,'project');project['delivery']='analysis';s.db.put(c,'project',project)
    assert '缺少分析交付与局限说明' in s.detail(o,p)['gates']['engineering']['blockers']
    with pytest.raises(ValueError,match='IntakePlan'):
        art(s,o,p,'AnalysisDelivery',{'conclusion':'QA','limits':'QA'},slot='project-intake')
