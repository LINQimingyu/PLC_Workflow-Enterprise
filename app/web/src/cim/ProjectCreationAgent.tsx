import { useEffect, useRef, useState } from "react";
import PlannerSettings from "./PlannerSettings";
import { plannerApi, type CreationCatalog, type CreationDraft, type CreationFields, type SetupPreview } from "./planner-model";
import "./planner.css";

const empty: CreationFields = { name: "", scenario: "", area: "", cpu: "", equipment: "", requirements: "", classification: "internal" };
export default function ProjectCreationAgent({ csrf, catalog, onCreated, onManual }: {
  csrf: string; catalog: CreationCatalog; onCreated: (id: string) => Promise<void>; onManual: () => void;
}) {
  const [brief, setBrief] = useState(""), [level, setLevel] = useState("pending"), [followup, setFollowup] = useState("");
  const [draft, setDraft] = useState<CreationDraft | null>(null), [fields, setFields] = useState<CreationFields>(empty);
  const [agentIds, setAgentIds] = useState<string[]>([]), [packIds, setPackIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<SetupPreview | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [requestId, setRequestId] = useState(localStorage.getItem("factory-planner-request") || "");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  async function apply(value: CreationDraft) {
    if (!alive.current || localStorage.getItem("factory-planner-request") !== value.id) return;
    setDraft(value); setPreview(null);
    if (value.status === "failed" || value.status === "uncertain") { setError(value.error || "规划未完成，未创建项目"); return; }
    if (!value.proposal) return;
    const values: CreationFields = { ...empty, ...Object.fromEntries(Object.entries(value.proposal.fields).map(([key, value]) => [key, value || ""])) };
    // A project may be more restricted than its planning brief, never less restricted.
    if (value.input_classification === "restricted") values.classification = "restricted";
    const packs = value.proposal.pack_ids.length ? value.proposal.pack_ids : catalog.process_packs.filter(p => p.area === values.area).map(p => p.id);
    setFields(values); setAgentIds(value.proposal.agent_ids); setPackIds(packs); setLevel(value.input_classification);
    if (["name", "scenario", "area", "cpu", "requirements"].every(key => values[key as keyof CreationFields])) {
      try {
        const result = await plannerApi<SetupPreview>(csrf, "project-setup/preview", { fields: values, agent_ids: value.proposal.agent_ids, pack_ids: packs });
        if (alive.current && localStorage.getItem("factory-planner-request") === value.id) setPreview(result);
      } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "请调整草案并重新预览配置"); }
    }
  }
  useEffect(() => {
    const saved = localStorage.getItem("factory-planner-request");
    if (saved) void plannerApi<CreationDraft>(csrf, `project-drafts/${encodeURIComponent(saved)}`).then(apply).catch(() => { if (alive.current) setError("上次请求未能读取，可重新读取状态或开始新的规划。"); });
  }, [csrf]);

  async function propose(continuation = false) {
    const id = crypto.randomUUID(); setRequestId(id); localStorage.setItem("factory-planner-request", id);
    setBusy(true); setError(""); setPreview(null); if (!continuation) setDraft(null);
    try {
      const result = await plannerApi<CreationDraft>(csrf, "project-drafts", { request_id: id,
        brief: continuation ? followup : brief, input_classification: level, ...(continuation && draft ? { parent_id: draft.id } : {}) });
      await apply(result); if (alive.current && continuation) setFollowup("");
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "请求未完成，请先读取请求状态"); }
    finally { if (alive.current) setBusy(false); }
  }
  async function recover() {
    if (!requestId) return; setBusy(true); setError("");
    try { await apply(await plannerApi<CreationDraft>(csrf, `project-drafts/${encodeURIComponent(requestId)}`)); }
    catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "请求状态读取失败"); }
    finally { if (alive.current) setBusy(false); }
  }
  async function inspect() {
    setBusy(true); setError(""); setPreview(null);
    try { const result = await plannerApi<SetupPreview>(csrf, "project-setup/preview", { fields, agent_ids: agentIds, pack_ids: packIds }); if (alive.current) setPreview(result); }
    catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "配置预览失败"); }
    finally { if (alive.current) setBusy(false); }
  }
  async function create() {
    if (!draft || !preview) return; setBusy(true); setError("");
    try {
      const result = await plannerApi<{ id: string }>(csrf, "project-setup/create", { draft_id: draft.id, fields, agent_ids: agentIds, pack_ids: packIds, fingerprint: preview.fingerprint });
      await onCreated(result.id);
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "创建未完成；重复提交相同配置不会重复建立项目"); }
    finally { if (alive.current) setBusy(false); }
  }
  function change(key: keyof CreationFields, value: string) { setFields(previous => ({ ...previous, [key]: value })); setPreview(null); }
  function toggle(kind: "agent" | "pack", id: string) {
    const setter = kind === "agent" ? setAgentIds : setPackIds;
    setter(previous => previous.includes(id) ? previous.filter(v => v !== id) : [...previous, id]); setPreview(null);
  }
  return <section className="pc-creator" aria-label="项目规划 Agent 创建向导">
    <div className="fc-surface"><span className="fc-eyebrow">PROJECT PLANNING AGENT</span><h2>让 Agent 协助创建项目</h2><p>描述你要解决的问题。Agent 整理需求、提出缺项，工作台自动组合专家、Skill、工艺包与任务依赖。</p>
      <div className="pc-create-path"><span>描述需求</span><b>→</b><span>澄清问题</span><b>→</b><span>预览能力配置</span><b>→</b><span>建立项目与任务</span></div>
      <PlannerSettings csrf={csrf} />
      <label className="fc-field"><span>可发送给模型的项目描述</span><textarea aria-label="项目规划描述" rows={5} value={brief} disabled={busy} onChange={e => setBrief(e.target.value)} placeholder="例如：FA 搬送线要新增马达负载上报。请协助梳理需求、需要的专业角色和后续步骤。已知 CPU、设备、范围可直接写明；未知项保留待问。" /></label>
      <div className="fc-actions"><label className="fc-field"><span>本次描述分级</span><select aria-label="规划描述分级" value={level} disabled={busy} onChange={e => setLevel(e.target.value)}>{["pending", "public", "internal", "restricted"].map(level => <option key={level}>{level}</option>)}</select></label><button type="button" disabled={busy || !brief.trim()} onClick={() => void propose()}>{busy ? "正在处理…" : "让 Agent 梳理需求"}</button><button type="button" className="secondary" disabled={busy} onClick={onManual}>改用手动填写</button></div>
      <p className="fc-muted">外部 API 只接收 public 描述；厂内模型按已确认部署位置处理已分级描述。已有项目和原始资料不会随创建请求读取。</p>
      {requestId && <div className="fc-actions"><small className="fc-muted">本次请求 {requestId}</small><button className="fc-link-button" disabled={busy} onClick={() => void recover()}>读取本次请求状态</button></div>}
      {draft?.status === "running" && <p role="status">请求已记录，模型正在处理。可稍后读取状态；不会自动重发模型请求。</p>}
      {error && <p className="pc-error" role="alert">{error}</p>}
    </div>
    {draft?.status === "completed" && draft.proposal && <>
      <section className="fc-surface"><h3>规划草案 · 待你核对</h3><p>{draft.proposal.summary}</p>
        {draft.created_project_id ? <div className="fc-actions"><p>该草案已创建项目，相同配置不会重复创建。</p><button onClick={() => void onCreated(draft.created_project_id!)}>打开已创建项目</button></div> : <>
          {draft.proposal.questions.length > 0 && <div className="pc-questions"><strong>Agent 需要进一步确认</strong><ol>{draft.proposal.questions.map((q, i) => <li key={i}>{q}</li>)}</ol></div>}
          <label className="fc-field"><span>补充说明或回答问题</span><textarea aria-label="规划补充说明" value={followup} onChange={e => setFollowup(e.target.value)} rows={3} /></label><button type="button" className="secondary" disabled={busy || !followup.trim()} onClick={() => void propose(true)}>提交补充并更新草案</button>
        </>}
      </section>
      {!draft.created_project_id && <section className="fc-surface"><h3>项目资料与能力配置</h3><fieldset disabled={busy}><p className="fc-muted">可直接修改草案。修改字段或勾选能力后，重新预览配置再创建。</p>
        <div className="fc-form-grid">
          {([["name", "规划项目名称"], ["cpu", "规划 CPU"], ["equipment", "规划设备类型"]] as const).map(([key, label]) => <label className="fc-field" key={key}><span>{label}</span><input aria-label={label} value={fields[key]} onChange={e => change(key, e.target.value)} /></label>)}
          <label className="fc-field"><span>规划场景</span><select aria-label="规划场景" value={fields.scenario} onChange={e => change("scenario", e.target.value)}><option value="">待确认</option><option value="fdc">CIM / FDC 改造</option><option value="tt">TT / 产能改善</option><option value="retrofit">工艺程序改造</option></select></label>
          <label className="fc-field"><span>规划工段</span><select aria-label="规划工段" value={fields.area} onChange={e => change("area", e.target.value)}><option value="">待确认</option>{["ARRAY", "CF", "CELL", "FA"].map(area => <option key={area}>{area}</option>)}</select></label>
          <label className="fc-field"><span>创建后项目分级</span><select aria-label="规划项目分级" value={fields.classification} onChange={e => change("classification", e.target.value)}>{["pending", "public", "internal", "restricted"].map(level => <option key={level}>{level}</option>)}</select></label>
        </div><label className="fc-field"><span>规划需求与验收范围</span><textarea aria-label="规划需求与验收范围" rows={5} value={fields.requirements} onChange={e => change("requirements", e.target.value)} /></label>
        <details className="pc-extra"><summary>补充专家选择 · 基础专家按场景与 CPU 自动加入</summary><div className="pc-choice-grid">{catalog.agents.map(a => <label className="pc-check" key={a.id}><input type="checkbox" checked={agentIds.includes(a.id)} onChange={() => toggle("agent", a.id)} /><span>{a.name}<small>{a.responsibility}</small></span></label>)}</div></details>
        <div className="pc-questions"><strong>绑定工艺能力包</strong><div className="pc-choice-grid">{catalog.process_packs.map(pack => <label className="pc-check" key={pack.id}><input type="checkbox" checked={packIds.includes(pack.id)} disabled={pack.area !== fields.area && !packIds.includes(pack.id)} onChange={() => toggle("pack", pack.id)} /><span>{pack.area} · {pack.id}<small>v{pack.version} · 候选 / 未现场验证</small></span></label>)}</div></div>
        <div className="fc-actions"><button type="button" className="secondary" disabled={busy} onClick={() => void inspect()}>预览专家、Skill 与任务流程</button><button type="button" disabled={busy || !preview} onClick={() => void create()}>按配置创建项目与任务</button></div>
        {preview && <div className="pc-preview"><div className="fc-metrics">{[["专家", preview.agents.length], ["Skill", preview.skills.length], ["工艺包", preview.process_packs.length], ["阶段", preview.stages.length]].map(([label, count]) => <div className="fc-metric" key={label}><span>{label}</span><strong>{count}</strong></div>)}</div>
          <p>创建后停留在需求澄清：专家任务为待执行，尚未自动运行或审查通过。</p>{preview.missing.map(message => <p className="fc-warning" key={message}>{message}</p>)}
          <div className="pc-setup-stages">{preview.stages.map(stage => <article key={stage.id}><h4>{stage.name}</h4><div className="fc-tags">{stage.agents.length ? stage.agents.map(id => <span key={id}>{preview.agents.find(a => a.id === id)?.name || id}</span>) : <span>人工执行并登记验证</span>}</div><small>{stage.completion}</small></article>)}</div>
          <details><summary>查看具体 Agent 与 Skill 组合</summary><div className="fc-table-scroll"><table><thead><tr><th>Agent / 职责</th><th>所用 Skill</th></tr></thead><tbody>{preview.agents.map(agent => <tr key={agent.id}><td><strong>{agent.name}</strong><small>{agent.responsibility}</small></td><td>{agent.skills.map(id => preview.skills.find(skill => skill.id === id)?.name || id).join("、")}</td></tr>)}</tbody></table></div></details>
        </div>}
      </fieldset></section>}
    </>}
  </section>;
}
