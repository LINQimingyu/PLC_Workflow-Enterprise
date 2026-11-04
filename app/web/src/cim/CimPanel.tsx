import { useEffect, useRef, useState, type FormEvent, type CSSProperties } from "react";
import "./factory.css";
import { ArchiveEditor, EstimateEditor } from "./BusinessForms";
import WorkflowMap from "./WorkflowMap";
import type { WorkflowAction, WorkflowSnapshot } from "./workflow-model";
import WorkflowGuide from "./WorkflowGuide";
import ProjectCreationAgent from "./ProjectCreationAgent";
import TaskWorkspace from "./TaskWorkspace";
import VerificationOverview from "./VerificationOverview";
import FontSizeControls, { useFontSize } from "./FontSizeControls";
import { FolderKanban, Route, Users, Library, Layers, ArrowUpRight } from "lucide-react";
import "./workspace-layout.css";

type Obj = Record<string, any>;
const statusNames: Obj = { queued: "待执行", waiting_return: "等待厂内回传", review: "待审查", approved: "已审查", rework: "返修", needs_info: "待补充", stale: "输入已过期", failed: "失败", cancelled: "已取消", active: "进行中", paused: "已暂停", archived: "已归档", candidate: "候选 · 未现场验证" };
const groupNames: Obj = { project: "项目协同", process: "面板工艺", engineering: "电气自动化", improvement: "产线改善", assurance: "验证与知识维护" };
const fmt = (v: unknown) => v == null ? "待确认" : typeof v === "number" ? v.toLocaleString("zh-CN", { maximumFractionDigits: 2 }) : String(v);
const pretty = (v: unknown) => JSON.stringify(v, null, 2);
function taskReturnDraft(task: Obj, attempt: Obj | undefined, results: Obj[]) {
  if (!attempt) return "";
  const result = results.find(r => r.task_id === task.id && r.attempt_id === attempt.id);
  const identity = ["project_id", "task_id", "attempt_id", "input_revision", "snapshot_hash"];
  const payload = ["summary", "verdict", "citations", "questions", "findings", "artifacts"];
  return pretty(result ? Object.fromEntries([...identity, ...payload].map(k => [k, result[k]])) : {
    ...Object.fromEntries(identity.map(k => [k, attempt.contract[k]])), summary: "", verdict: "needs_info", citations: [], questions: [], findings: [], artifacts: [],
  });
}
const emptyEstimate = { bom: [{ action: "new", spec: "", quantity: 1, unit_price: null, source: "" }], labor: { investigation: null, design: null, programming: null, testing: null, onsite: null, documentation: null }, daily_rate: null, benefit: { kind: "estimated", annual_value: null, basis: "" }, assumptions: [] };
const emptyArchive = { outcome: "not_implemented", reason: "", actor: "", comparison: {}, actual_investment: {}, remaining: [] };
const emptyModel = { config: { stations: [{ id: "S1", process_seconds: 10, parallel: 1 }, { id: "S2", process_seconds: 20, parallel: 1 }], buffers: [1], release_interval_seconds: 10, duration_seconds: 3600, warmup_seconds: 0 }, scenario: { stations: [{ id: "S1", process_seconds: 10, parallel: 1 }, { id: "S2", process_seconds: 15, parallel: 1 }] }, observed_completed: null, tolerance: 0.1 };

function Json({ value, label = "查看完整记录" }: { value: unknown; label?: string }) {
  return <details className="fc-json"><summary>{label}</summary><pre>{pretty(value)}</pre></details>;
}
function Badge({ value }: { value: string }) { return <span className={`fc-badge ${value}`}>{statusNames[value] || value}</span>; }
function Field({ name, children }: { name: string; children: React.ReactNode }) { return <label className="fc-field"><span>{name}</span>{children}</label>; }

export default function CimPanel() {
  const [fontPercent, setFontPercent] = useFontSize();
  const [session, setSession] = useState<Obj | null>(null), [token, setToken] = useState("");
  const [projects, setProjects] = useState<Obj[]>([]), [catalog, setCatalog] = useState<Obj>({ agents: [], skills: [], process_packs: [] });
  const [pid, setPid] = useState(""), [detail, setDetail] = useState<Obj | null>(null);
  const selectedProject = useRef(localStorage.getItem("factory-selected-project") || "");
  const loadedProject = useRef("");
  const [page, setPage] = useState("projects"), [tab, setTab] = useState("overview"), [filter, setFilter] = useState("");
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false), [output, setOutput] = useState<unknown>(null);
  const [createMode, setCreateMode] = useState("manual");
  const [workflowTarget, setWorkflowTarget] = useState<WorkflowAction | null>(null);
  const [workflowSnapshot, setWorkflowSnapshot] = useState<WorkflowSnapshot | null>(null);
  const [draft, setDraft] = useState<Obj>({ name: "", scenario: "fdc", area: "FA", cpu: "Q26UDV", equipment: "", classification: "internal", requirements: "" });
  const [upload, setUpload] = useState({ kind: "source", classification: "pending" });
  const [projectLevel, setProjectLevel] = useState("internal");
  const [query, setQuery] = useState(""), [hits, setHits] = useState<Obj[]>([]);
  const [beforeId, setBeforeId] = useState(""), [afterId, setAfterId] = useState(""), [sourceId, setSourceId] = useState(""), [terminal, setTerminal] = useState("");
  const [actor, setActor] = useState(""), [reviewNote, setReviewNote] = useState("");
  const [taskSelected, setTaskSelected] = useState<Obj | null>(null), [returned, setReturned] = useState("");
  const [requirements, setRequirements] = useState("");
  const [model, setModel] = useState(pretty({ config: { stations: [{ id: "S1", process_seconds: 10, parallel: 1 }, { id: "S2", process_seconds: 20, parallel: 1 }], buffers: [1], release_interval_seconds: 10, duration_seconds: 3600, warmup_seconds: 0 }, scenario: { stations: [{ id: "S1", process_seconds: 10, parallel: 1 }, { id: "S2", process_seconds: 15, parallel: 1 }] }, observed_completed: null, tolerance: 0.1 }));
  const [estimate, setEstimate] = useState(pretty({ bom: [{ action: "new", spec: "", quantity: 1, unit_price: null, source: "" }], labor: { investigation: null, design: null, programming: null, testing: null, onsite: null, documentation: null }, daily_rate: null, benefit: { kind: "estimated", annual_value: null, basis: "" }, assumptions: [] }));
  const [verification, setVerification] = useState({ phase: "compile", status: "not_run", record: "", source_id: "" });
  const [archive, setArchive] = useState(pretty({ outcome: "not_implemented", reason: "", actor: "", comparison: {}, actual_investment: {}, remaining: [] }));

  async function api(path: string, body?: unknown) {
    const response = await fetch(path, { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json", ...(session?.csrf ? { "x-csrf-token": session.csrf } : {}) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || `操作未完成 (${response.status})`);
    return data;
  }
  async function load(selected = selectedProject.current) {
    const [p, c] = await Promise.all([api("/api/cim/projects"), api("/api/cim/catalog")]);
    setProjects(p.projects); setCatalog(c);
    const id = p.projects.some((p: Obj) => p.id === selected) ? selected : p.projects[0]?.id;
    if (id) {
      selectedProject.current = id; localStorage.setItem("factory-selected-project", id); setPid(id);
      const d = await api(`/api/cim/projects/${id}`);
      if (loadedProject.current !== id) {
        loadedProject.current = id;
        setEstimate(pretty(d.estimates.at(-1)?.input || emptyEstimate));
        const archiveRecord = d.archives.at(-1);
        setArchive(pretty(archiveRecord ? Object.fromEntries(Object.keys(emptyArchive).map(key => [key, archiveRecord[key]])) : emptyArchive));
        setModel(pretty(d.analyses.filter((a: Obj) => a.kind === "simulate").at(-1)?.result.configuration || emptyModel));
        setBeforeId(""); setAfterId(""); setSourceId(""); setTerminal(""); setHits([]); setQuery(""); setTaskSelected(null); setReturned(""); setWorkflowTarget(null);
        setVerification({ phase: "compile", status: "not_run", record: "", source_id: "" });
        setReviewNote("");
      }
      setDetail(d); setRequirements(d.project.requirements); setProjectLevel(d.project.classification);
    }
  }
  async function run(action: () => Promise<unknown>, message = "已保存") {
    setBusy(true); setError(""); setNotice("");
    try { const result = await action(); setOutput(result); await load(); setNotice(message); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function command(action: string, data: Obj = {}) {
    return api(`/api/cim/projects/${pid}/commands/${action}`, data);
  }
  async function login(value: string) {
    try { const s = await api("/api/session", { token: value }); setSession(s); history.replaceState(null, "", "#cim"); }
    catch (e) { setError(String(e)); }
  }
  useEffect(() => {
    const incoming = new URLSearchParams(location.hash.slice(1).split("?")[1] || "").get("token");
    if (incoming) void login(incoming);
    else void api("/api/session").then(s => setSession(s.authenticated ? s : {})).catch(() => setSession({}));
  }, []);
  useEffect(() => { if (session?.authenticated) void load().catch(e => setError(String(e))); }, [session?.authenticated]);
  useEffect(() => { window.scrollTo(0, 0); }, [page, tab, pid]);
  useEffect(() => {
    if (!workflowTarget) return;
    const timer = window.setTimeout(() => {
      const key = workflowTarget.task_id ? "data-task-id" : workflowTarget.document_id ? "data-document-id" : workflowTarget.record_id ? "data-record-id" : "data-workflow-focus";
      const value = workflowTarget.task_id || workflowTarget.document_id || workflowTarget.record_id || workflowTarget.focus || (workflowTarget.phase ? "verification" : workflowTarget.tab);
      const matches = document.querySelectorAll<HTMLElement>(`[${key}="${CSS.escape(value)}"]`);
      const element = matches.item(matches.length - 1) || document.querySelector<HTMLElement>("[data-workflow-content]");
      element?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "center" });
      element?.classList.add("wf-navigation-highlight");
      element?.setAttribute("tabindex", "-1"); element?.focus({ preventScroll: true });
    }, 80);
    return () => { clearTimeout(timer); document.querySelectorAll(".wf-navigation-highlight").forEach(e => e.classList.remove("wf-navigation-highlight")); };
  }, [workflowTarget]);
  const project = detail?.project;
  const rev = project?.revision;
  const docs: Obj[] = detail?.documents.filter((d: Obj) => !d.revoked) || [];
  const tasks: Obj[] = detail?.tasks || [];
  const revisionTasks = tasks.filter(t => t.revision === rev);
  const approved = revisionTasks.filter(t => t.status === "approved").length;
  const sourceOptions = <><option value="">选择项目资料</option>{docs.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</>;

  async function uploadFile(file: File) {
    const data: string = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file); });
    return command("document", { expected_revision: rev, name: file.name, data_base64: data, ...upload });
  }
  async function start(task: Obj) {
    const a = await command("start", { task_id: task.id, request_id: crypto.randomUUID() });
    setTaskSelected(task);
    setReturned(pretty({ ...Object.fromEntries(["project_id", "task_id", "attempt_id", "input_revision", "snapshot_hash"].map(k => [k, a.contract[k]])), summary: "", verdict: "needs_info", citations: [], questions: [], findings: [], artifacts: [] }));
    return a;
  }
  function selectTask(task: Obj) {
    setTaskSelected(task);
    const a = detail?.attempts.find((a: Obj) => a.id === task.current_attempt);
    setReturned(taskReturnDraft(task, a, detail?.results || []));
  }

  async function navigateWorkflow(target: WorkflowAction) {
    try {
      const fresh = await api(`/api/cim/projects/${pid}`);
      if (selectedProject.current !== pid) return;
      setDetail(fresh); setRequirements(fresh.project.requirements); setProjectLevel(fresh.project.classification);
      setPage("projects"); setTab(target.tab); setOutput(null);
      if (target.task_id) {
        const task = fresh.tasks.find((t: Obj) => t.id === target.task_id);
        if (task) {
          setTaskSelected(task);
          const attempt = fresh.attempts.find((a: Obj) => a.id === task.current_attempt);
          setReturned(taskReturnDraft(task, attempt, fresh.results));
        }
      }
      if (target.document_id) {
        const document = fresh.documents.find((d: Obj) => d.id === target.document_id);
        if (document?.revoked) setOutput(document);
      }
      if (target.phase) setVerification(previous => ({ ...previous, phase: target.phase! }));
      setWorkflowTarget({ ...target });
    } catch (e) { setError(e instanceof Error ? e.message : "无法读取最新项目，请刷新后再试"); }
  }

  if (!session?.authenticated) return <div className="factory-app fc-login"><div className="fc-login-card"><div className="fc-brand-mark">F</div><h1>面板工厂工程工作台</h1><p>使用本机启动器提供的操作员凭证登录。</p><form onSubmit={(e: FormEvent) => { e.preventDefault(); void login(token); }}><input type="password" aria-label="操作员凭证" value={token} onChange={e => setToken(e.target.value)} autoComplete="off" /><button>进入工作台</button></form>{error && <p role="alert">{error}</p>}</div></div>;

  return <div className="factory-app" style={{ "--fc-font-scale": fontPercent / 100 } as CSSProperties}>
    <aside className="fc-sidebar"><a className="fc-brand" href="#cim"><span className="fc-brand-mark">F</span><div>TFT-LCD<span>工程与改善工作台</span></div></a>
      <p className="fc-nav-caption">工作空间</p>{[["projects", FolderKanban, "项目工作台"], ["workflow", Route, "工作流"]].map(([id, Icon, label]) => { const Mark = Icon as typeof FolderKanban; return <button type="button" key={String(id)} className={page === id ? "selected" : ""} aria-current={page === id ? "page" : undefined} onClick={() => setPage(String(id))}><Mark size={18} aria-hidden="true" />{String(label)}</button>; })}
      <p className="fc-nav-caption">知识与能力</p>{[["agents", Users, "专家目录"], ["skills", Library, "Skill 方法库"], ["packs", Layers, "工艺能力包"]].map(([id, Icon, label]) => { const Mark = Icon as typeof Users; return <button type="button" key={String(id)} className={page === id ? "selected" : ""} aria-current={page === id ? "page" : undefined} onClick={() => setPage(String(id))}><Mark size={18} aria-hidden="true" />{String(label)}</button>; })}
      <p className="fc-nav-caption">工程底座</p><a className="fc-native" href="#engineering"><ArrowUpRight size={16} aria-hidden="true" />GXWorks 原生工程工作台</a>
      <div className="fc-sidebar-foot"><span className="fc-dot" />厂内资料 · 本机运行<small>gxworks-agent · c3a0f0b1<br />工厂扩展 v0.1.0</small></div>
    </aside>
    <a className="fc-skip" href="#factory-content">跳至项目内容</a><main id="factory-content" className="fc-main" tabIndex={-1}><header className="fc-top"><div><span className="fc-eyebrow">FACTORY ENGINEERING</span><h1>{page === "projects" ? "项目工作台" : page === "workflow" ? "工作流 · 完整使用路线" : page === "agents" ? "专业 Agent 目录" : page === "skills" ? "Skill 方法库" : "工艺能力包"}</h1></div><div className="fc-header-actions"><FontSizeControls percent={fontPercent} onChange={setFontPercent} /><span className="fc-local">● LOCAL</span><button className="secondary" disabled={busy} onClick={() => void run(() => load(), "已刷新")}>刷新</button></div></header>
      {(error || notice) && <div className={`fc-message ${error ? "error" : ""}`} role={error ? "alert" : "status"}>{error || notice}<button aria-label="关闭操作提示" onClick={() => { setError(""); setNotice(""); }}>×</button></div>}
      {page === "workflow" ? <WorkflowGuide csrf={session.csrf} hasProject={!!pid} onNavigate={navigateWorkflow} onCreate={() => { setPage("projects"); setCreateMode("agent"); setShowCreate(true); }} /> : page !== "projects" ? <>
        <div className="fc-intro"><h2>{page === "agents" ? `${catalog.agents.length} 个专业角色，按项目组合` : page === "skills" ? `${catalog.skills.length} 个可复用方法` : "ARRAY / CF / CELL / FA"}</h2><p>目录已建立。专家分析通过厂内任务包执行；设备参数、现场验证与成熟度分别记录。</p><input placeholder="搜索名称、领域或方法…" aria-label="搜索能力目录" value={filter} onChange={e => setFilter(e.target.value)} /></div>
        {page === "packs" && <section className="fc-surface pc-pack-intro"><h3>工艺能力包：把工艺知识带进项目任务</h3><p>Agent 负责分析，Skill 提供方法，工艺能力包提供同一工段的工序、约束、配方、来源与案例。使用 Agent 协助新建项目时，可自动选定并绑定工艺包，与角色和 Skill 一起进入任务快照。</p><p>当前四个包仍是候选骨架，现场参数、约束、来源与责任人确认待补充。具体操作和交接见工作流页。</p><button className="secondary" onClick={() => setPage("workflow")}>查看完整工作流</button></section>}
        {page === "agents" && catalog.creation_agent && <section className="fc-surface pc-pack-intro"><h3>{catalog.creation_agent.name} · 新建项目前置 Agent</h3><p>{catalog.creation_agent.responsibility}</p><button className="secondary" onClick={() => { setPage("projects"); setCreateMode("agent"); setShowCreate(true); }}>使用规划 Agent 创建项目</button></section>}
        <div className="fc-cards">{(page === "agents" ? catalog.agents : page === "skills" ? catalog.skills : catalog.process_packs).filter((x: Obj) => pretty(x).toLowerCase().includes(filter.toLowerCase())).map((x: Obj) => <article className="fc-card" key={x.id}><div className="fc-card-top"><span className="fc-eyebrow">{groupNames[x.category] || x.category || x.area}</span><span>v{x.version}</span></div><h3>{x.name || x.id}</h3><Badge value={x.status} /><p>{x.responsibility || x.inputs?.join("；") || x.unknowns?.join("；")}</p>{x.skills && <div className="fc-tags">{x.skills.map((s: string) => <span key={s}>{catalog.skills.find((k: Obj) => k.id === s)?.name || s}</span>)}</div>}<code>{x.path}</code><Json value={x} label="职责、输入输出与适用范围" /></article>)}</div>
      </> : <>
        <div className="fc-project-row"><select aria-label="选择业务项目" value={pid} onChange={e => { setPid(e.target.value); setTaskSelected(null); setOutput(null); void run(() => load(e.target.value), "项目已切换"); }}>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><button onClick={() => { setCreateMode("manual"); setShowCreate(!showCreate); }}>＋ 新建项目</button><button className="secondary" onClick={() => { setCreateMode("agent"); setShowCreate(true); }}>AI 协助创建</button></div>
        {showCreate && <nav className="pc-mode-nav" aria-label="新建项目方式"><button className={createMode === "manual" ? "" : "secondary"} onClick={() => setCreateMode("manual")}>手动填写</button><button className={createMode === "agent" ? "" : "secondary"} onClick={() => setCreateMode("agent")}>Agent 协助创建</button><button className="secondary" onClick={() => setShowCreate(false)}>关闭创建向导</button></nav>}
        {showCreate && createMode === "agent" && <ProjectCreationAgent csrf={session.csrf} catalog={{ agents: catalog.agents, process_packs: catalog.process_packs }} onManual={() => setCreateMode("manual")} onCreated={async id => { await load(id); setShowCreate(false); setNotice("已创建项目并配置专家、Skill、工艺包与待执行任务"); }} />}
        {showCreate && createMode === "manual" && <form className="fc-surface fc-form" onSubmit={e => { e.preventDefault(); void run(async () => { const p = await api("/api/cim/projects", draft); setPid(p.id); await load(p.id); setShowCreate(false); return p; }, "项目已建立"); }}><h2>新建业务项目</h2><div className="fc-form-grid">{[["name", "项目名称"], ["equipment", "设备类型 / 机台"], ["cpu", "控制平台 / CPU"]].map(([key, label]) => <Field key={key} name={label}><input required={key === "name"} value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></Field>)}<Field name="场景"><select value={draft.scenario} onChange={e => setDraft({ ...draft, scenario: e.target.value })}><option value="fdc">CIM / FDC 改造</option><option value="tt">TT / 产能改善</option><option value="retrofit">工艺程序改造</option></select></Field><Field name="工段"><select value={draft.area} onChange={e => setDraft({ ...draft, area: e.target.value })}>{["ARRAY", "CF", "CELL", "FA"].map(x => <option key={x}>{x}</option>)}</select></Field><Field name="项目资料分级"><select value={draft.classification} onChange={e => setDraft({ ...draft, classification: e.target.value })}>{["pending", "internal", "restricted", "public"].map(x => <option key={x}>{x}</option>)}</select></Field></div><Field name="现状、目标、范围与验收要求"><textarea value={draft.requirements} onChange={e => setDraft({ ...draft, requirements: e.target.value })} /></Field><button disabled={busy}>建立项目</button></form>}
        {!project || project.id !== pid ? <div className="fc-empty"><h2>从一张 CIM 需求单开始</h2><p>新建项目，收集资料，再按实际工段和控制平台组织专家。</p></div> : <>
          <section className="fc-project-head" data-workflow-focus="project"><div><div className="fc-tags"><span>{project.area}</span><span>{project.cpu}</span><span>{project.classification}</span><span>输入版本 r{rev}</span></div><h2>{project.name}</h2><p>{project.equipment || "设备类型待补充"}</p></div><div className="fc-project-status"><Badge value={project.status} /><button className="secondary" disabled={busy || !["active", "paused"].includes(project.status)} onClick={() => void run(() => command("status", { status: project.status === "paused" ? "active" : "paused" }), "项目状态已更新")}>{project.status === "paused" ? "恢复项目" : "暂停项目"}</button></div></section>
          <WorkflowMap key={pid} projectId={pid} fontScale={fontPercent / 100} refreshKey={detail} onNavigate={navigateWorkflow} onSnapshot={setWorkflowSnapshot} />
          {workflowTarget && <div className="wf-navigation-note" role="status">流程导航：{workflowTarget.label}<button className="wf-text-button" onClick={() => setWorkflowTarget(null)}>关闭定位提示</button></div>}
          <nav className="fc-tabs" data-workflow-content>{[["overview", "项目概览"], ["documents", "资料与检索"], ["tasks", "专家任务"], ["analysis", "FDC / TT 工具"], ["business", "方案与投入"], ["delivery", "验证与归档"]].map(([id, label]) => <button className={tab === id ? "selected" : ""} key={id} onClick={() => { setTab(id); setOutput(null); }}>{label}</button>)}</nav>
          {tab === "overview" && <>
            <div className="fc-metrics">{[["资料基线", docs.filter(d => d.kind === "source").length, "原件独立保存"], ["当前任务", revisionTasks.length, "按需组织专家"], ["已审查", `${approved} / ${revisionTasks.length}`, "输入变化后重新确认"], ["待确认", detail?.route.missing.length, "不自动补造现场事实"]].map(([label, value, hint]) => <div className="fc-metric" key={label}><span>{label}</span><strong>{value}</strong><small>{hint}</small></div>)}</div>
            <div className="fc-two-col"><section className="fc-surface"><h3 data-workflow-focus="requirements">需求与验收范围</h3><textarea aria-label="需求与验收范围" rows={7} value={requirements} onChange={e => setRequirements(e.target.value)} /><div className="fc-actions"><button disabled={busy} onClick={() => void run(() => command("update", { expected_revision: rev, requirements }), "输入已更新；旧任务保留为历史")}>保存需求新版本</button><input placeholder="确认人" aria-label="确认人" value={actor} onChange={e => setActor(e.target.value)} /><button className="secondary" disabled={busy} onClick={() => void run(() => command("confirm", { expected_revision: rev, actor }), "当前需求已确认")}>{project.requirements_confirmed ? "已确认 · 可重新确认" : "确认当前需求"}</button></div></section><section className="fc-surface"><h3>下一步</h3>{detail?.route.missing.map((m: string) => <p className="fc-warning" key={m}>{m}</p>)}{workflowSnapshot?.project_id === pid ? <><p>{workflowSnapshot.recommended.label}</p>{workflowSnapshot.blockers.map(b => <p className="fc-warning" key={b}>{b}</p>)}{workflowSnapshot.recommended.focus === "plan" ? <button disabled={busy} onClick={() => void run(() => command("plan", { expected_revision: rev }), "当前输入版本的任务已建立")}>生成本项目专家任务</button> : <button disabled={busy} onClick={() => navigateWorkflow(workflowSnapshot.recommended)}>前往处理</button>}</> : <p className="fc-muted">正在读取当前项目流程，请查看上方流程地图。</p>}<p className="fc-muted">在流程地图展开节点，可查看责任、输入、成果和真实前置依赖。</p></section></div>
            <section className="fc-surface"><h3 data-workflow-focus="engineering">本项目专家组合</h3>{project.configuration && <div className="pc-config-note">由项目规划 Agent 辅助创建 · 已配置本项目专家与 Skill · 工艺包：{project.configuration.pack_ids.join("、") || "未绑定"}<br />配置按工段、设备与 CPU 生效；后续执行与审查逐步完成。</div>}<div className="fc-tags">{detail?.route.agents.map((s: Obj) => <span key={s.agent.id}>{s.agent.name} · v{s.agent.version}</span>)}</div><Json value={project.engineering} label="关联工程与不可变版本" /><EngineeringLink busy={busy} link={(values: Obj) => void run(() => command("link", { expected_revision: rev, ...values }), "工程版本已关联，任务需按新基线执行")} /></section>
          </>}
          {tab === "documents" && <><section className="fc-surface"><h3 data-workflow-focus="classification">收集资料</h3><div className="fc-actions"><span>项目当前分级：{project.classification}</span><select aria-label="项目分级" value={projectLevel} onChange={e => setProjectLevel(e.target.value)}>{["pending", "internal", "restricted", "public"].map(level => <option key={level}>{level}</option>)}</select><button className="secondary" disabled={busy || projectLevel === project.classification} onClick={() => void run(() => command("update", { expected_revision: rev, classification: projectLevel }), "项目分级已更新；请重新确认当前版本")}>保存项目分级</button></div><p className="fc-muted">需求、图纸、点表、配方和日志作为来源；候选成果与验证证据单独保存。原生工程可转至 GXWorks 工程工作台。</p><div className="fc-actions"><select aria-label="资料用途" value={upload.kind} onChange={e => setUpload({ ...upload, kind: e.target.value })}><option value="source">来源资料（改变输入版本）</option><option value="candidate">候选成果</option><option value="evidence">验证证据</option></select><select aria-label="资料分级" value={upload.classification} onChange={e => setUpload({ ...upload, classification: e.target.value })}>{["pending", "internal", "restricted", "public"].map(x => <option key={x}>{x}</option>)}</select><label className="fc-file-button">＋ 导入文件<input type="file" disabled={busy} onChange={e => { const f = e.target.files?.[0]; if (f) void run(() => uploadFile(f), "资料已保存；来源资料变化会使旧任务过期"); e.target.value = ""; }} /></label></div><div className="fc-table-scroll"><table><thead><tr><th>文件</th><th>用途 / 分级</th><th>解析状态</th><th>来源指纹</th><th>操作</th></tr></thead><tbody>{docs.map(d => <tr key={d.id} data-document-id={d.id}><td>{d.name}<small>{fmt(d.size)} bytes</small></td><td>{d.kind}<small>{d.classification}</small></td><td>{d.parse_status}</td><td><code title={d.sha256}>{d.sha256.slice(0, 14)}…</code></td><td><a href={`/api/cim/projects/${pid}/documents/${d.id}`}>下载原件</a><button className="fc-link-button" onClick={() => void run(() => command("revoke", { doc_id: d.id, expected_revision: rev, reason: reviewNote }), "资料已撤销，依赖任务已过期")}>撤销</button><ClassifyDocument busy={busy} classify={(level: string) => void run(() => command("classify", { doc_id: d.id, expected_revision: rev, classification: level, actor, reason: reviewNote }), "资料分级已更新")} /></td></tr>)}</tbody></table></div><div className="fc-actions"><input aria-label="资料分级责任人" placeholder="分级责任人" value={actor} onChange={e => setActor(e.target.value)} /><input aria-label="资料变更依据" placeholder="分级或撤销依据" value={reviewNote} onChange={e => setReviewNote(e.target.value)} /></div></section><section className="fc-surface"><h3>厂内证据检索</h3><p className="fc-muted">本机字符词项与特征向量检索；只查询本项目及经批准、同工段和 CPU 的共享案例。回答由厂内任务 Agent 引用证据形成。</p><form className="fc-actions" onSubmit={e => { e.preventDefault(); void run(async () => { const r = await api(`/api/cim/projects/${pid}/search?q=${encodeURIComponent(query)}&include_shared=true`); setHits(r.citations); return r; }, "检索完成"); }}><input aria-label="检索词" value={query} onChange={e => setQuery(e.target.value)} placeholder="例如：马达负载、数据缩放、断线处理" /><button disabled={busy}>检索证据</button></form>{hits.map((h, i) => <article className="fc-hit" key={i}><strong>{h.name}</strong><span>{h.location} · {h.sha256.slice(0, 12)}</span><p>{h.text}</p></article>)}</section></>}
          {tab === "tasks" && <><div className="fc-actions" data-workflow-focus="plan"><button disabled={busy} onClick={() => void run(() => command("plan", { expected_revision: rev }), "当前任务已生成")}>生成当前版本任务</button><span className="fc-muted">按依赖处理；选择任务后在详情中载入回传与审查。</span></div>
            <TaskWorkspace tasks={tasks} revision={rev} projectId={pid} classification={project.classification}
              selected={taskSelected} snapshot={workflowSnapshot} busy={busy} returned={returned} onReturned={setReturned}
              onSelect={selectTask} onStart={t => void run(() => start(t), "批次已创建，请下载任务包")}
              onSubmit={() => void run(() => command("submit", { result: JSON.parse(returned) }), "回传已保存；尚未人工审查")}
              onFileError={setError} actor={actor} onActor={setActor} note={reviewNote} onNote={setReviewNote}
              onReview={decision => void run(() => command("review", { task_id: taskSelected!.id, decision, actor, note: reviewNote }), "审查已记录")}
              results={detail?.results || []} badge={value => <Badge value={value} />} />
          </>}
          {tab === "analysis" && <><div className="fc-two-col"><section className="fc-surface"><h3>FDC / PLC 原程序核查</h3><p className="fc-muted">复用 gxworks-agent CSV 解析与差异工具。该入口只读；候选程序另存，通过原生工程工作台验证。</p><Field name="修改前 / 分析来源"><select value={beforeId} onChange={e => setBeforeId(e.target.value)}>{sourceOptions}</select></Field><Field name="修改后"><select value={afterId} onChange={e => setAfterId(e.target.value)}>{sourceOptions}</select></Field><div className="fc-actions"><button disabled={busy || !beforeId || !afterId} onClick={() => void run(() => command("csv-compare", { expected_revision: rev, before_id: beforeId, after_id: afterId }), "静态前后对照已保存")}>生成前后对照</button><button className="secondary" disabled={busy || !beforeId} onClick={() => void run(() => command("csv-inspect", { expected_revision: rev, source_id: beforeId, cpu: project.cpu }), "原程序读取结果已保存")}>分析原程序</button></div></section><section className="fc-surface"><h3>TT 日志质量与瓶颈候选</h3><p className="fc-muted">先检查事件配对、时区、重复和并行设备。服务能力代理用于定位候选，整线收益仍需校准与实测。</p><Field name="事件 CSV"><select value={sourceId} onChange={e => setSourceId(e.target.value)}>{sourceOptions}</select></Field><Field name="产出统计末站"><input placeholder="例如 S3，须与日志 station 一致" value={terminal} onChange={e => setTerminal(e.target.value)} /></Field><button disabled={busy || !sourceId || !terminal} onClick={() => void run(() => command("tt-analyze", { expected_revision: rev, source_id: sourceId, terminal_station: terminal }), "日志核查与分析已保存")}>核查日志并分析</button></section></div><section className="fc-surface"><h3>SimPy 基线校准与情景比较</h3><p className="fc-muted">当前模型支持串行工序、并行机、有限缓存及完工后阻塞。须绑定基线日志，填写同窗口实测完成数；误差超限停止预测。</p><Field name="基线证据"><select value={sourceId} onChange={e => setSourceId(e.target.value)}>{sourceOptions}</select></Field><textarea className="fc-code-input" rows={12} aria-label="仿真模型配置" value={model} onChange={e => setModel(e.target.value)} /><button disabled={busy || !sourceId} onClick={() => void run(() => command("simulate", { expected_revision: rev, source_ids: [sourceId], ...JSON.parse(model) }), "模型校准与情景结果已保存")}>执行校准与情景比较</button></section>{detail?.analyses.map((a: Obj) => <AnalysisCard key={a.id} analysis={a} current={rev} />)}</>}
          {tab === "business" && <section className="fc-surface"><h3>BOM、人天与投入收益</h3><p className="fc-muted">数量、价格、费率和收益分别标注依据；未确认的价格和人天保留为空。收益分预计、实测和非货币，不自动替你作投资决策。</p><EstimateEditor value={estimate} onChange={setEstimate} /><button disabled={busy} onClick={() => void run(() => command("estimate", { expected_revision: rev, data: JSON.parse(estimate) }), "投入收益测算已保存")}>核算并保存方案</button>{detail?.estimates.map((e: Obj) => <div className="fc-estimate" key={e.id} data-record-id={e.id}><div className="fc-metrics"><div className="fc-metric"><span>已知投入小计</span><strong>{fmt(e.result.known_cost_subtotal)}</strong></div><div className="fc-metric"><span>总投入</span><strong>{fmt(e.result.total_cost)}</strong></div><div className="fc-metric"><span>工作人天</span><strong>{fmt(e.result.person_days)}</strong></div><div className="fc-metric"><span>回收年限</span><strong>{fmt(e.result.payback_years)}</strong></div></div>{e.result.unknowns.map((x: string) => <p className="fc-warning" key={x}>{x}</p>)}<Json value={e} label={`输入 r${e.revision} 的方案依据`} /></div>)}</section>}
          {tab === "delivery" && <><VerificationOverview records={detail?.verification || []} revision={rev} snapshot={workflowSnapshot?.project_id === pid ? workflowSnapshot : null} onSelect={phase => { setVerification(previous => ({ ...previous, phase })); setWorkflowTarget({ label: "登记验证证据", tab: "delivery", focus: "verification", phase }); }} /><section className="fc-surface"><h3 data-workflow-focus="verification">工程、现场与效益分别验收</h3><div className="fc-form-grid"><Field name="阶段"><select aria-label="验证阶段" value={verification.phase} onChange={e => setVerification({ ...verification, phase: e.target.value })}>{[["static", "静态检查"], ["compile", "GX 编译"], ["simulation", "模拟验证"], ["field", "现场验证"], ["benefit", "效果对照"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field><Field name="结果"><select value={verification.status} onChange={e => setVerification({ ...verification, status: e.target.value })}>{[["not_run", "未验证"], ["passed", "通过 · 已登记证据"], ["failed", "失败"], ["not_applicable", "有理由豁免"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field><Field name="执行人"><input value={actor} onChange={e => setActor(e.target.value)} /></Field><Field name="原始验证资料（用途须为 evidence）"><select value={verification.source_id} onChange={e => setVerification({ ...verification, source_id: e.target.value })}><option value="">选择验证证据</option>{docs.filter(d => d.kind === "evidence").map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field></div><Field name="步骤、预期、实际与版本说明"><textarea value={verification.record} onChange={e => setVerification({ ...verification, record: e.target.value })} /></Field><button disabled={busy} onClick={() => void run(() => command("verify", { expected_revision: rev, phase: verification.phase, status: verification.status, actor, record: verification.record, source_ids: verification.source_id ? [verification.source_id] : [] }), "人工验证证据已登记")}>登记验证记录</button>{detail?.verification.map((v: Obj) => <article key={v.id} data-record-id={v.id}><p className="fc-muted">输入 r{v.revision} · {v.phase} · {v.status} · {v.actor}</p><Json value={v} label="查看此验证记录与证据" /></article>)}</section><section className="fc-surface"><h3 data-workflow-focus="archive">前后对照与项目归档</h3><p className="fc-muted">实施归档检查当前审查和工程验证。未实施、取消也可记录原因；效益观察中与实测完成分开归档。</p><Json label="实施归档 comparison 字段示例" value={{ baseline: "改前数据", after: "改后数据或待观察", metric_definition: "同一计算公式", product_recipe: "同产品配方", window: "同长度观察窗口", effect_status: "pending_observation", confounders: [], source_ids: [] }} /><ArchiveEditor value={archive} onChange={setArchive} documents={docs} /><div className="fc-actions"><button disabled={busy} onClick={() => void run(() => command("archive", { expected_revision: rev, ...JSON.parse(archive) }), "归档状态已记录")}>检查并归档</button>{["archived", "cancelled"].includes(project.status) && <a className="fc-file-button" href={`/api/cim/projects/${pid}/archive-bundle`}>下载完整归档包</a>}<button className="secondary" onClick={() => void run(() => api(`/api/cim/projects/${pid}/audit`), "审计记录已读取")}>查看审计轨迹</button></div>{detail?.archives.map((a: Obj) => <div key={a.id} data-record-id={a.id}><Json value={a} label="归档记录" /></div>)}</section></>}
          {output != null && <section className="fc-surface fc-output"><Json value={output} label="本次操作结果与完整证据" /></section>}
        </>}
      </>}
      <footer className="fc-footer">工程候选、编译接受、现场通过与实测收益分别记录。工艺包与专家的现场成熟度以证据为准。</footer>
    </main>
  </div>;
}

function EngineeringLink({ busy, link }: { busy: boolean; link: (values: Obj) => void }) {
  const [project, setProject] = useState(""), [version, setVersion] = useState("");
  return <div className="fc-actions"><input placeholder="上游工程 ID" aria-label="上游工程 ID" value={project} onChange={e => setProject(e.target.value)} /><input placeholder="不可变 version_id" aria-label="工程版本 ID" value={version} onChange={e => setVersion(e.target.value)} /><button className="secondary" disabled={busy || !project || !version} onClick={() => link({ engineering_id: project, version_id: version })}>关联工程版本</button></div>;
}
function ClassifyDocument({ busy, classify }: { busy: boolean; classify: (level: string) => void }) {
  const [level, setLevel] = useState("internal");
  return <span className="fc-classify"><select aria-label="变更资料分级" value={level} onChange={e => setLevel(e.target.value)}>{["internal", "restricted", "public", "pending"].map(x => <option key={x}>{x}</option>)}</select><button className="fc-link-button" disabled={busy} onClick={() => classify(level)}>分级</button></span>;
}
function AnalysisCard({ analysis: a, current }: { analysis: Obj; current: number }) {
  const r = a.result;
  return <section className="fc-surface" data-record-id={a.id}><div className="fc-card-top"><h3>{a.kind} · 输入 r{a.revision}</h3><Badge value={a.revision === current ? "candidate" : "stale"} /></div>{r.quality && <p>日志质量：{r.quality === "passed" ? "基础检查通过" : "检查未通过"} {r.synthetic && "（合成演示数据）"}</p>}{r.stations && <><p>末站完成 {r.completed} 片 · {fmt(r.throughput_per_hour)} 片/小时 · 瓶颈候选 {r.bottleneck_candidate}</p>{r.stations.map((s: Obj) => <div className="fc-bar" key={s.station}><span>{s.station}</span><div><i style={{ width: `${100 * s.effective_service_seconds / Math.max(...r.stations.map((x: Obj) => x.effective_service_seconds))}%` }} /></div><strong>{fmt(s.mean_seconds)} s / {s.parallel} 台</strong></div>)}</>}{r.calibrated !== undefined && <p>{r.calibrated ? `基线已校准；预计完成数变化 ${fmt(r.delta_completed)}` : "基线校准未通过，未输出改善预测"}</p>}{r.record_counts && <p>CSV 记录数 {r.record_counts[0]} → {r.record_counts[1]} · 静态来源对照，编译 / 运行 / 现场验证待完成</p>}<Json value={a} label="原始结果、引用、假设与限制" /></section>;
}
