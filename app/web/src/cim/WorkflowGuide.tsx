import { useEffect, useState } from "react";
import PlannerSettings from "./PlannerSettings";
import { plannerApi, type CreationAgentDefinition } from "./planner-model";
import type { WorkflowAction, WorkflowTab } from "./workflow-model";
import "./planner.css";

interface GuideStage {
  id: string; number: number; name: string; role: string; purpose: string; tab: WorkflowTab;
  inputs: string[]; operations: string[]; outputs: string[]; completion: string; handoff: string; rework: string;
  agents: { id: string; name: string; skills: string[] }[];
}
interface Guide {
  title: string; stages: GuideStage[]; creation_agent: CreationAgentDefinition; task_cycle: string[];
  process_packs: { id: string; area: string; status: string; unknowns: string[]; constraint_count: number; step_count: number; source_count: number }[];
}
export default function WorkflowGuide({ csrf, hasProject, onNavigate, onCreate }: {
  csrf: string; hasProject: boolean; onNavigate: (action: WorkflowAction) => void; onCreate: () => void;
}) {
  const [guide, setGuide] = useState<Guide | null>(null), [error, setError] = useState("");
  const [selected, setSelected] = useState("requirements"), [all, setAll] = useState(false);
  useEffect(() => { let active = true; void plannerApi<Guide>(csrf, "workflow-guide").then(value => { if (active) setGuide(value); }).catch(e => { if (active) setError(String(e)); }); return () => { active = false; }; }, [csrf]);
  if (!guide) return <section className="fc-surface">{error || "正在读取工作台流程…"}</section>;
  return <div className="wg-guide" aria-label="工作台完整流程说明">
    <section className="fc-surface wg-intro"><span className="fc-eyebrow">HOW THE WORKBENCH WORKS</span><h2>从需求到归档，每一步怎么做</h2><p>这页说明工作台的完整使用路线。具体项目的当前位置与待办，查看项目内的“项目流程地图”。</p>
      <div className="fc-actions"><button onClick={onCreate}>由项目规划 Agent 协助创建</button><button className="secondary" disabled={!hasProject} onClick={() => onNavigate({ label: "查看当前项目流程", tab: "overview" })}>查看当前项目流程</button><button className="secondary" onClick={() => setAll(!all)}>{all ? "逐阶段阅读" : "展开全部步骤"}</button></div>
    </section>
    <section className="fc-surface wg-preflight"><div><span className="fc-eyebrow">创建前置步骤</span><h3>{guide.creation_agent.name}</h3><p>{guide.creation_agent.responsibility}</p><p className="fc-muted">输入需求描述 → 提出澄清问题 → 预览专家 / Skill / 工艺包 → 创建项目与待执行任务。后续执行与审查由你逐步推进。</p></div><div className="fc-tags">{guide.creation_agent.skills.map(id => <span key={id}>创建 Skill · {id}</span>)}</div></section>
    <PlannerSettings csrf={csrf} />
    <nav className="wg-route" aria-label="七阶段使用路线">{guide.stages.map(stage => <button key={stage.id} className={selected === stage.id ? "selected" : "secondary"} onClick={() => { setSelected(stage.id); setAll(false); }}><small>{String(stage.number).padStart(2, "0")}</small>{stage.name}</button>)}</nav>
    {(all ? guide.stages : guide.stages.filter(s => s.id === selected)).map(stage => <article className="fc-surface wg-stage" key={stage.id} data-guide-stage={stage.id}>
      <div className="wg-stage-heading"><div><span className="fc-eyebrow">STEP {stage.number} / 7</span><h2>{stage.name}</h2><p>{stage.purpose}</p></div><button className="secondary" disabled={!hasProject} onClick={() => onNavigate({ label: `前往${stage.name}`, tab: stage.tab })}>前往当前项目处理 ↗</button></div>
      <div className="wg-io"><div><h3>进入前准备什么</h3><ul>{stage.inputs.map((s, i) => <li key={i}>{s}</li>)}</ul></div><div><h3>谁来处理</h3><p>{stage.role}</p><div className="fc-tags">{stage.agents.map(a => <span key={a.id}>{a.name}</span>)}</div><small className="fc-muted">专家目录按阶段列出，实际项目依场景、工段、设备和 CPU 组合。</small></div></div>
      <h3>在工作台怎样操作</h3><ol className="wg-operations">{stage.operations.map((operation, i) => <li key={i}><b>{i + 1}</b><span>{operation}</span></li>)}</ol>
      <div className="wg-io"><div><h3>这一步产出什么</h3><ul>{stage.outputs.map((s, i) => <li key={i}>{s}</li>)}</ul></div><div><h3>什么时候算完成</h3><p>{stage.completion}</p></div></div>
      <div className="wg-handoff"><strong>如何交给下一步</strong><p>{stage.handoff}</p></div><div className="wg-rework"><strong>资料不足或需要修改时</strong><p>{stage.rework}</p></div>
      {!all && <div className="fc-actions wg-step-nav"><button className="secondary" disabled={stage.number === 1} onClick={() => setSelected(guide.stages[stage.number - 2].id)}>← 上一步</button><span>{stage.number} / 7</span><button className="secondary" disabled={stage.number === 7} onClick={() => setSelected(guide.stages[stage.number].id)}>下一步 →</button></div>}
    </article>)}
    <section className="fc-surface"><h3>一个专家任务如何走完</h3><div className="pc-create-path">{guide.task_cycle.map((state, i) => <span key={state}>{i > 0 && <b> → </b>}{state}</span>)}</div><p className="fc-muted">暂停、过期、取消和返修分别记录。前置任务未通过时，下游任务保持等待。</p></section>
    <section className="fc-surface wg-pack-help"><h3>工艺能力包有什么用</h3><p>工艺能力包把同一工段的工序、约束、配方、来源、相关专家和案例组织在一起。项目创建时选定包，工作台将其与专家及 Skill 一起放入任务快照，帮助后续任务检查工艺前提和缺项。</p>
      <div className="wg-io"><div><h4>Agent</h4><p>谁来分析：承担职责、产出成果。</p><h4>Skill</h4><p>怎样分析：提供方法、步骤与判断边界。</p></div><div><h4>工艺能力包</h4><p>依据什么工艺分析：提供该工段的工序与约束上下文。</p><h4>工作流</h4><p>何时交接：组织依赖、人工接受与验证步骤。</p></div></div>
      <div className="pc-choice-grid">{guide.process_packs.map(pack => <article className="wg-pack" key={pack.id}><strong>{pack.area} · {pack.id}</strong><p>候选骨架 · 尚未现场验证</p><small>工序 {pack.step_count} · 约束 {pack.constraint_count} · 来源 {pack.source_count}</small><p>待补充：{pack.unknowns.join("、")}</p></article>)}</div>
    </section>
  </div>;
}
