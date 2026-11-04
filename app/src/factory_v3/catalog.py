"""Definitions are capabilities; templates, not agents, create module instances."""
from copy import deepcopy
from cim.registry import Registry, digest

ROLES = {"owner":"项目总控／设备改造负责人", "plc":"PLC／设备自动化工程师", "equipment":"设备工程师",
         "cim":"CIM 工程师", "process":"工艺工程师", "production":"生产／制造", "quality":"品质", "ie":"IE／效率改善", "electrical":"电气工程师"}
SPECS = {
 "controller": ("总控", ["requirements","impact-scope","evidence-baseline","proposal","archive"], ["business.estimate"]),
 "plc": ("PLC 工程", ["sequence-recovery","minimal-patch","hmi","motion","pneumatic-vacuum"], ["plc.inspect_csv","plc.compare_csv"]),
 "cim": ("CIM", ["fdc-contract","fdc-retrospective"], ["plc.inspect_csv","plc.compare_csv"]),
 "efficiency": ("TT／效率", ["event-quality","timeline","bottleneck","buffer-flow","dispatch","uptime","resource-efficiency","simpy-scenarios","benefit-compare"], ["tt.analyze","tt.simulate"]),
 "process": ("工艺约束", ["process-map","recipe-consistency"], []),
 "electrical": ("电气辅助", ["bom-io","impact-scope"], ["business.estimate"]),
 "review": ("工程审查", ["program-review","process-review"], ["plc.inspect_csv","plc.compare_csv"]),
 "verification": ("验证与效果", ["test-evidence","benefit-compare"], [])}
SCENARIOS = {"fdc":"CIM · FDC 上报", "tt":"TT 改善", "process_optimization":"工艺优化", "retrofit":"设备改造"}
HUMAN_GATES = {"scope","baseline","proposal","implementation","verification","archive"}

def catalog():
    r=Registry()
    agents=[]
    for aid,(name,skills,tools) in SPECS.items():
        agents.append({"id":aid,"name":name,"version":"3.0.0","skills":skills,"tools":["knowledge.search","evidence.read"]+tools,"status":"candidate","field_validated":False})
    return {"agents":agents,"roles":ROLES,"scenarios":SCENARIOS,"skills":list(r.skills.values()),"process_packs":list(r.packs.values()),"human_gates":sorted(HUMAN_GATES),"execution_modes":["manual","bundle","api"]}

def definition(aid,cpu="",equipment="",area=""):
    r=Registry()
    a=next(deepcopy(a) for a in catalog()["agents"] if a["id"]==aid)
    if aid=="plc":
        if cpu.upper().startswith("Q"): a["skills"].append("q-source")
        elif cpu.upper().startswith("R"): a["skills"].append("r-source")
    if aid=="process":
        route=r.route({"scenario":"retrofit","area":area,"cpu":cpu,"equipment":equipment})
        for snap in route["agents"]:
            if snap["agent"]["category"]=="process": a["skills"]+=snap["agent"]["skills"]
    a["skills"]=list(dict.fromkeys(a["skills"]))
    skills=[{**r.skills[s],"instructions":(r.root/r.skills[s]["path"]).with_name("SKILL.md").read_text(encoding="utf-8")} for s in a["skills"]]
    result={"agent":a,"skills":skills,"process_packs":[p for p in r.packs.values() if p["area"]==area] if aid=="process" else []}
    result["sha256"]=digest(result)
    return result

def template(scenarios,implementation=False,electrical=False):
    if not scenarios or set(scenarios)-SCENARIOS.keys(): raise ValueError("请选择有效项目目标")
    rows=[]
    def add(key,label,agent,deps,role,outputs):
        rows.append({"key":key,"label":label,"agent_id":agent,"dependencies":deps,"responsible_role":role,
                     "outputs":outputs,"review_mode":"human","mandatory_human":key in HUMAN_GATES})
    add("scope","范围与验收","controller",[],"owner",["现状、目标、纳入/排除、验收与缺项"])
    add("baseline","资料与工程基线","controller",["scope"],"plc",["资料哈希、工程版本与适用性"])
    analyses=[]
    for scenario in dict.fromkeys(scenarios):
        key={"fdc":"cim","tt":"efficiency","process_optimization":"process","retrofit":"plc"}[scenario]
        if key in analyses: continue
        analyses.append(key)
        add(key,SPECS[key][0]+"分析",key,["baseline"],{"cim":"cim","efficiency":"ie","process":"process","plc":"plc"}[key],
            {"cim":["点表、类型/单位/缩放、有效性、采样与异常"],"efficiency":["日志质量、同口径窗口、损失与瓶颈依据"],"process":["动作与工艺窗口、配方一致性、约束来源"],"plc":["顺控联锁、异常恢复与改造影响"]}[key])
    if electrical:
        analyses.append("electrical"); add("electrical","电气影响分析","electrical",["baseline"],"electrical",["I/O、图纸、BOM、施工与回退"])
    add("proposal","方案与实施决定","controller",analyses,"owner",["方案比较、影响、停机/回退、预计收益及未知项"])
    prior="proposal"
    if implementation:
        add("implementation","PLC 候选实现","plc",[prior],"plc",["候选程序、最小差异、回退及正常/异常/恢复用例"]); prior="implementation"
    add("review","工程审查","review",[prior],"plc",["逐项审查、阻断问题、证据与返修清单"])
    add("verification","验证与效果交接","verification",["review"],"owner",["静态、编译、模拟、现场、效果分别记录；未实施说明"])
    add("archive","最终交付与归档","controller",["verification"],"owner",["实际结局、对照、剩余事项与可复用交付"])
    return rows
