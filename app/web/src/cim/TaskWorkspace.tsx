import { useId, useRef, type ReactNode } from "react";
import { FileInput, ListChecks } from "lucide-react";
import type { WorkflowSnapshot } from "./workflow-model";

type Obj = Record<string, any>;
interface Props {
  tasks: Obj[]; revision: number; projectId: string; classification: string;
  selected: Obj | null; snapshot: WorkflowSnapshot | null; busy: boolean;
  returned: string; onReturned: (value: string) => void;
  onSelect: (task: Obj) => void; onStart: (task: Obj) => void;
  onSubmit: () => void; onFileError: (message: string) => void;
  actor: string; onActor: (value: string) => void;
  note: string; onNote: (value: string) => void;
  onReview: (decision: string) => void; results: Obj[];
  badge: (status: string) => ReactNode;
}
const stages: Record<string, string> = { requirements: "需求澄清", baseline: "资料基线", analysis: "专业分析", proposal: "方案评估", review: "专业审查", verification: "工程与现场验证", archive: "归档对照" };

export default function TaskWorkspace(p: Props) {
  const file = useRef<HTMLInputElement>(null), heading = useRef<HTMLHeadingElement>(null);
  const id = useId();
  const lookup = p.snapshot?.project_id === p.projectId && p.snapshot.revision === p.revision ? p.snapshot : null;
  const node = (task: Obj) => lookup?.nodes.find(n => n.id === `task:${task.id}`);
  const taskState = (task: Obj) => node(task)?.status || task.status;
  const current = p.tasks.filter(t => t.revision === p.revision && taskState(t) !== "stale");
  const history = p.tasks.filter(t => t.revision !== p.revision || taskState(t) === "stale");
  const pending = current.filter(t => !["approved", "cancelled"].includes(t.status));
  const actionable = pending.filter(t => node(t)?.ready);
  const waiting = pending.filter(t => !node(t)?.ready);
  const completed = current.filter(t => ["approved", "cancelled"].includes(t.status));
  const selected = p.tasks.find(t => t.id === p.selected?.id) || null;
  const selectedNode = selected ? node(selected) : undefined;
  const isCurrent = !!selected && selected.revision === p.revision && taskState(selected) !== "stale";
  const canReturn = isCurrent && selected?.status === "waiting_return" && !!selectedNode?.ready;
  const canReview = isCurrent && !!selectedNode?.ready;
  let parsed: Obj | null = null, parseError = "";
  if (p.returned.trim()) {
    try {
      const value = JSON.parse(p.returned);
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("回传必须为 JSON 对象");
      parsed = value;
    } catch { parseError = "回传文件不是有效的 JSON 对象，请检查文件内容后重新载入。"; }
  }
  const contractMismatch = !!parsed && !!selected && (parsed.task_id !== selected.id || parsed.project_id !== p.projectId || parsed.input_revision !== p.revision || parsed.attempt_id !== selected.current_attempt);
  function choose(task: Obj) {
    p.onSelect(task);
    if (window.matchMedia("(max-width: 1050px)").matches) requestAnimationFrame(() => heading.current?.focus());
  }
  function group(label: string, tasks: Obj[], historical = false) {
    return <section className="fc-task-group" aria-label={label}>
      <h3>{label}<span>{tasks.length}</span></h3>
      {!tasks.length && <p className="fc-muted">{historical ? "暂无历史任务。" : "暂无此类任务。"}</p>}
      {tasks.map(t => <article key={t.id} data-task-id={t.id} className={`fc-task-row ${selected?.id === t.id ? "is-selected" : ""}`}>
        <button type="button" className="fc-task-select" aria-pressed={selected?.id === t.id} onClick={() => choose(t)}>
          <span><small>{stages[t.stage] || t.stage} · 输入 r{t.revision}</small><strong>{t.definition.agent.name}</strong></span>
          {p.badge(taskState(t))}
        </button>
        <p className="fc-task-reason">{historical ? "历史成果保留，不计入当前版本完成数量。" : node(t)?.blockers[0] || (t.status === "waiting_return" ? "厂内人工任务包 · 等待载入结果" : t.status === "review" ? "回传已保存，等待工程师审查" : node(t)?.ready ? "前置条件已满足，可查看并处理" : lookup ? "按依赖与任务合同继续处理" : "正在读取任务可执行条件…")}</p>
        <div className="fc-task-row-actions">
          <button type="button" className="secondary" onClick={() => choose(t)}>查看 / 回传</button>
          {!historical && ["queued", "needs_info", "rework", "failed"].includes(t.status) && <button type="button" disabled={p.busy || !node(t)?.ready} onClick={() => p.onStart(t)}>创建执行批次</button>}
          {t.current_attempt && <a href={`/api/cim/projects/${p.projectId}/attempts/${t.current_attempt}/bundle`}>下载任务包</a>}
        </div>
      </article>)}
    </section>;
  }
  return <div className="fc-task-workspace">
    <div className="fc-surface fc-task-list" aria-label="项目任务列表">
      <div className="fc-section-title"><h2><ListChecks size={18} aria-hidden="true" />当前版本任务</h2><span className="fc-muted">输入 r{p.revision}</span></div>
      {group("当前可处理", actionable)}
      {!!waiting.length && <details className="fc-task-history fc-task-waiting"><summary>等待前置或状态更新 · {waiting.length}</summary>{group("等待前置或状态更新", waiting)}</details>}
      {!!completed.length && <details className="fc-task-history"><summary>已审查 / 已取消 · {completed.length}</summary>{group("当前版本已结束任务", completed)}</details>}
      {!!history.length && <details className="fc-task-history"><summary>历史版本任务 · {history.length}</summary>{group("历史版本", history, true)}</details>}
    </div>
    <section className="fc-surface fc-task-detail" data-task-id={selected?.id} aria-label="选中任务详情">
      <h2 ref={heading} tabIndex={-1}>{selected ? `${selected.definition.agent.name} · 任务回传` : "选择任务查看详情"}</h2>
      {!selected ? <p className="fc-muted">从左侧选择任务，查看责任、输入、前置依赖与回传结果。</p> : <>
        <div className="fc-task-context">{p.badge(taskState(selected))}<span>输入 r{selected.revision} · Agent v{selected.definition.agent.version}</span></div>
        {!isCurrent && <p className="fc-warning">此任务属于历史输入或已过期，只供查看；请处理当前版本任务。</p>}
        <dl className="fc-task-facts"><dt>任务职责</dt><dd>{selectedNode?.purpose || selected.definition.agent.responsibility}</dd><dt>输入与完成条件</dt><dd>{selectedNode?.inputs.join("；") || "查看本批次来源快照。"}</dd><dd>{selectedNode?.completion || "按任务合同完成分析，并经工程师审查。"}</dd></dl>
        {!!selectedNode?.blockers.length && <div className="fc-warning"><strong>当前阻塞</strong><ul>{selectedNode.blockers.map(b => <li key={b}>{b}</li>)}</ul></div>}
        <details className="fc-json"><summary>本批次职责、完整 Skill 与工具权限</summary><pre>{JSON.stringify(selected.definition, null, 2)}</pre></details>
        {selected.current_attempt ? <>
          <h3 className="fc-form-heading">1. 载入并核对回传</h3>
          <div className="fc-actions"><button type="button" className="secondary" disabled={p.busy || !canReturn} onClick={() => file.current?.click()}><FileInput size={16} aria-hidden="true" />载入回传 JSON</button><input ref={file} hidden type="file" accept=".json,application/json" aria-label="选择任务回传文件" onChange={async e => { const f = e.target.files?.[0]; e.target.value = ""; if (f) try { p.onReturned(await f.text()); } catch { p.onFileError("回传文件读取失败，请重新选择文件。"); } }} /></div>
          {parseError && <p className="fc-warning" role="alert">{parseError}</p>}
          {contractMismatch && <p className="fc-warning" role="alert">回传的项目、任务、输入版本或批次不匹配，请选择本批次的回传文件。</p>}
          {parsed && <div className="fc-return-summary" aria-label="回传摘要"><dl className="fc-task-facts"><dt>结论摘要</dt><dd>{typeof parsed.summary === "string" && parsed.summary.trim() ? parsed.summary : "尚未填写分析结论"}</dd><dt>回传判断</dt><dd>{({ candidate: "候选成果", needs_info: "待补充" } as Record<string, string>)[parsed.verdict] || String(parsed.verdict || "未填写")}</dd><dt>证据引用</dt><dd>{Array.isArray(parsed.citations) ? `${parsed.citations.length} 条；提交前请核对来源。` : "引用格式待检查"}</dd></dl></div>}
          <details className="fc-return-editor"><summary>查看 / 编辑回传 JSON</summary><textarea className="fc-code-input" rows={10} aria-label="任务回传 JSON" spellCheck={false} value={p.returned} onChange={e => p.onReturned(e.target.value)} /></details>
          <button type="button" disabled={p.busy || !canReturn || !parsed || !!parseError || contractMismatch} onClick={p.onSubmit}>提交回传</button>
          {p.results.some(r => r.attempt_id === selected.current_attempt) && <p className="fc-muted">本批次已回传；返修需创建新执行批次。</p>}
          {p.classification === "public" && <p><a href={`/api/cim/projects/${p.projectId}/attempts/${selected.current_attempt}/bundle?destination=external`}>豆包 / Codex 用包（public）</a></p>}
        </> : <p className="fc-muted">创建执行批次后，可下载任务包并载入回传。</p>}
        <h3 className="fc-form-heading">2. 工程师审查</h3><p className="fc-muted">提交回传后才进入人工审查；载入文件不会自动接受成果。</p>
        <div className="fc-review-fields"><label className="fc-field" htmlFor={`${id}-actor`}><span>审查人</span><input id={`${id}-actor`} name="reviewer" autoComplete="off" value={p.actor} onChange={e => p.onActor(e.target.value)} /></label><label className="fc-field" htmlFor={`${id}-note`}><span>审查意见 / 返修依据</span><textarea id={`${id}-note`} aria-label="审查意见" name="review-note" rows={3} value={p.note} onChange={e => p.onNote(e.target.value)} /></label></div>
        <div className="fc-actions">{[["approve", "审查通过"], ["rework", "退回返修"], ["cancel", "取消任务"]].map(([decision, label]) => <button type="button" className="secondary" key={decision} disabled={p.busy || !canReview || (decision === "approve" && selected.status !== "review")} onClick={() => p.onReview(decision)}>{label}</button>)}</div>
        <details className="fc-json"><summary>历次回传与审查状态</summary><pre>{JSON.stringify(p.results.filter(r => r.task_id === selected.id), null, 2)}</pre></details>
      </>}
    </section>
  </div>;
}
