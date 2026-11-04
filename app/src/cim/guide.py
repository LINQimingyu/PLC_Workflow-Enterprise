"""Creator-facing workflow instructions backed by the actual stage catalog."""
from .registry import agent_stage
from .workflow import STAGE_INFO

DETAILS={
 "requirements":{
  "inputs":["现状、目标、设备范围、纳入与排除项","验收指标、责任人、尚不确定的问题"],
  "operations":["手动新建，或由项目规划 Agent 对话整理草案并预览能力组合","核对需求文本、工段、CPU 和设备范围；输入确认人并确认当前版本","执行项目协调与需求专家任务，回传成果后由工程师审查"],
  "outputs":["当前版本需求与验收范围","缺项清单、需求专家已审查成果"],
  "handoff":"确认按钮与专家任务是两项独立工作，完成后进入资料基线。",
  "rework":"需求或来源改变后生成新输入版本；旧任务保留历史，重新确认需求。"},
 "baseline":{
  "inputs":["图纸、点表、原程序、工艺资料、配方与日志","资料分级、来源哈希、上游工程不可变版本"],
  "operations":["在资料与检索中导入原件，区分来源、候选成果、验证证据","核对解析状态与分级，按需检索具体行、页、表坐标","在项目概览关联原生工程的明确版本；执行并审查基线专家任务"],
  "outputs":["可追溯资料清单与工程绑定","本次任务可引用的基线和证据坐标"],
  "handoff":"基线专家任务通过后，依合同开启专业分析；缺资料不等于可以推定现场事实。",
  "rework":"撤销资料、调整分级或重绑工程会使旧任务过期，需要按新版本重新执行。"},
 "analysis":{
  "inputs":["当前需求与资料基线","本项目专家、Skill 和工艺包快照","前置任务已接受成果"],
  "operations":["在专家任务中查看职责、Skill、工具权限和前置依赖","创建执行批次并下载 ZIP，在厂内批准的 AI 中处理","载入回传 JSON，检查结论与引用，再人工审查通过或返修","按需使用 FDC 静态核查、TT 日志分析；TT 校准须绑定同版本基线日志"],
  "outputs":["有来源的专业分析与候选方案","分析工具记录、问题与限制"],
  "handoff":"任务包当前采用人工交接；创建批次仅表示等待回传，不能算任务已完成。",
  "rework":"待补充、失败或返修须处理原因后创建新批次；旧批次延迟回传只进入历史。"},
 "proposal":{
  "inputs":["已审查的专业分析与候选方案","BOM 数量、报价依据、人天、费率、收益口径"],
  "operations":["执行并审查可行性专家任务","在方案与投入中记录新增、复用、替换物料与各类人天","保存投入收益测算；未知价格保持未知，预计与实测收益分别填写"],
  "outputs":["方案评估成果","BOM、人天、成本、收益依据及未知项"],
  "handoff":"完成方案专家审查后进入专业审查；测算是决策依据，不代表批准投资或实现收益。",
  "rework":"方案或范围改变时回到对应输入和专业任务，更新版本与依据。"},
 "review":{
  "inputs":["候选成果、逻辑差异和来源引用","工艺约束、适用范围、验收与回退要求"],
  "operations":["按依赖执行程序、工艺和证据审查专家","查看候选回传与缺项，具名填写人工审查意见","通过后继续；不足则退回返修，取消也须记录原因"],
  "outputs":["分别记录的程序、工艺、证据审查结论","具名人工接受或返修依据"],
  "handoff":"审查通过表示接受当前候选与证据，不等于编译、模拟或现场验收通过。",
  "rework":"返修产生新执行批次；输入变更则使相关旧任务失效。"},
 "verification":{
  "inputs":["明确的当前工程版本与候选程序","人工执行步骤、预期、实际及原始 evidence 文件"],
  "operations":["通过原生工程工作台或人工 GX 工具执行实际编译和模拟","现场由责任人验证行为与回退条件","在验证与归档分别登记静态、编译、模拟、现场、效果五类记录","通过须附原始证据；不适用须说明理由，每项采用当前版本最新记录"],
  "outputs":["分别登记的工程与现场验证记录","原始证据和版本关联；效果可注明仍在观察"],
  "handoff":"已实施归档要求四项工程验证完成或有理由豁免；实测效果另需效果验证与原始数据。",
  "rework":"失败回到对应方案或工程任务处理，重新验证；不得以静态检查代替真实编译或现场证据。"},
 "archive":{
  "inputs":["实际实施结局、审查与验证证据","同口径前后对照、实际投入、剩余事项"],
  "operations":["完成归档专家成果整理","填写已实施、未实施或取消的结局与原因、责任人","已实施项目填写同产品配方、同窗口、同公式的对照；效果区分实测和观察中","检查并归档，下载归档包；经责任人批准后再共享案例"],
  "outputs":["具名归档结局、完整资料包与操作轨迹","经批准可复用的厂内案例"],
  "handoff":"归档专家任务和项目正式归档分别记录；未实施或取消归档不会把前面阶段全部标成通过。",
  "rework":"案例撤回会使使用它的活动项目失效；历史结局与未解决项继续保留。"},
}


def workflow_guide(registry,creation_agent):
    stages=[]
    for index,(sid,info) in enumerate(STAGE_INFO.items()):
        stages.append({"id":sid,"number":index+1,"name":info[0],"role":info[1],"purpose":info[2],"tab":info[3],"completion":info[4],
                       "previous":list(STAGE_INFO)[index-1] if index else None,
                       "next":list(STAGE_INFO)[index+1] if index+1<len(STAGE_INFO) else None,
                       "agents":[{"id":a["id"],"name":a["name"],"skills":a["skills"]} for a in registry.agents.values() if agent_stage(a)==sid],
                       **DETAILS[sid]})
    return {"title":"工作台工作流","stages":stages,"creation_agent":creation_agent,
            "task_cycle":["待执行","创建批次 / 等待厂内回传","载入回传","人工审查","通过进入下游 / 返修再执行"],
            "process_packs":[{**p,"constraint_count":len(p["constraints"]),"step_count":len(p["steps"]),"source_count":len(p["sources"])} for p in registry.packs.values()]}
