"""Work is organized by deliverables, not by the number of agents."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    'control': ('项目总控与基线', '项目负责人', ['ToolchainProfile', 'RequirementSpec', 'EngineeringPlan'], ['control.dispatch','control.review']),
    'plc': ('PLC／HMI 工程', 'PLC／自动化工程师', ['CodeBundle'], ['plc.inspect_csv', 'plc.compare_csv']),
    'diagnosis': ('故障诊断与维护', '设备维护工程师', ['DiagnosisCase'], ['diagnosis.check']),
    'electrical': ('电气设计与改造', '电气工程师', ['ElectricalDesignPackage'], ['electrical.calculate']),
    'improvement': ('工艺与产能改善', '工艺／IE 工程师', ['ImprovementPackage'], ['tt.analyze']),
    'energy': ('能耗与运行优化', '能源／运行工程师', ['EnergyBaseline'], ['energy.calculate']),
    'review': ('工程审查与风险管理', '独立工程审核人', ['RiskFinding'], []),
    'validation': ('真实工具验证', '验证工程师', ['CompileResult', 'SimulationReport'], ['vendor.compile', 'vendor.simulate']),
    'delivery': ('文档与工程交付', '项目交付负责人', ['EngineeringReleaseManifest'], []),
    'knowledge': ('知识治理', '知识管理员与领域审核人', ['KnowledgeVersion'], []),
}
ARTIFACTS = {
    'IntakePlan': ['scope', 'tasks', 'missing'],
    'ToolchainProfile': ['device', 'cpu', 'firmware', 'ide', 'ide_version', 'libraries', 'original_ids', 'permissions'],
    'RequirementSpec': ['goal', 'scope', 'exclusions', 'acceptance', 'key_io', 'interlocks'],
    'EngineeringPlan': ['solution', 'validation', 'rollback', 'impact'],
    'CodeBundle': ['changes', 'io', 'tests', 'rollback'],
    'ElectricalDesignPackage': ['parameters', 'calculations', 'bom', 'drawing_draft', 'construction_impact'],
    'DiagnosisCase': ['context', 'hypotheses', 'evidence', 'counterevidence', 'checks', 'outcome'],
    'ImprovementPackage': ['scope', 'data_definition', 'baseline', 'bottleneck', 'constraints', 'proposal'],
    'EnergyBaseline': ['period', 'boundary', 'energy_kwh', 'good_units', 'operating_states', 'tariff', 'quality'],
    'CompileResult': ['job_id'], 'SimulationReport': ['job_id'],
    'RiskFinding': ['severity', 'description', 'mitigation', 'rollback'],
    'ManualInterventionRecord': ['reason', 'failed_rounds'],
    'EngineeringReleaseManifest': ['scope'], 'KnowledgeVersion': ['applicability', 'validation_depth'],
    'Original': ['source', 'classification'], 'AnalysisDelivery': ['conclusion', 'limits'],
    'PatchProposal': ['base_id', 'failure_job_id', 'reason', 'rollback'],
}
GATES = ['input', 'plan', 'engineering', 'risk', 'release', 'knowledge']
GATE_NAMES = dict(zip(GATES, ['输入锁', '方案锁', '工程锁', '风险锁', '发布锁', '知识锁']))
STAGES = ['static', 'compile', 'simulation', 'field', 'benefit']

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()

def catalog():
    return {'modules': [{'id': k, 'name': v[0], 'responsible_role': v[1], 'outputs': v[2], 'tools': v[3],
                         'skill': k, 'agent_optional': True} for k, v in MODULES.items()],
            'artifact_types': ARTIFACTS, 'gates': GATE_NAMES, 'stages': STAGES,
            'roles': ['owner', 'engineer', 'reviewer', 'validator', 'knowledge', 'viewer'],
            'runtime': 'LangGraph', 'database': 'PostgreSQL', 'offline_first': True}

def method(module):
    if module not in MODULES:
        raise ValueError('未知工作模块')
    p = ROOT / 'enterprise_skills' / module / 'SKILL.md'
    text = p.read_text(encoding='utf-8')
    return {'id': module, 'instructions': text, 'sha256': digest(text.encode())}

def legacy_support(module,context,cpu):
    if context is None:return {'snapshots':[],'missing':[],'status':'not_selected'}
    if not isinstance(context,dict) or set(context)!={'scenario','area','equipment'} or not all(context.values()):
        raise ValueError('上游专业方法需明确 scenario、area、equipment；不推测设备上下文')
    if context['area'] not in {'ARRAY','CF','CELL','FA'} or context['scenario'] not in {'fdc','tt','retrofit'}:
        raise ValueError('上游方法场景或工段无效')
    if not cpu:raise ValueError('先明确 CPU 基线，再选用上游专业方法')
    from cim.registry import Registry
    routed=Registry().route({**context,'cpu':cpu})
    def relevant(agent):
        ident,category=agent['id'],agent['category']
        if module=='control':return category=='project'
        if module=='plc':return category=='engineering' and ident not in {'electrical','cim-fdc'}
        if module=='improvement':return category in {'improvement','process'} or ident=='cim-fdc'
        if module=='electrical':return ident=='electrical'
        if module=='diagnosis':return ident in {'sequence','pneumatic-vacuum','motion'}
        if module=='review':return ident in {'program-review','process-review'}
        if module=='validation':return ident=='evidence-review'
        if module=='delivery':return ident=='archive'
        return False
    return {'snapshots':[s for s in routed['agents'] if relevant(s['agent'])], 'missing':routed['missing'],
            'status':'candidate_supporting_methods','process_packs':routed['process_packs']}
