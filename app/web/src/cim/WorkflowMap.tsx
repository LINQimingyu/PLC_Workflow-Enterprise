import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, Handle, MiniMap, Position, ReactFlow,
  type Node, type NodeProps, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { workflowGraph, workflowStatus, statusMark, type StageId, type WorkflowAction,
  type WorkflowHistory, type WorkflowNode, type WorkflowSnapshot } from "./workflow-model";
import "./workflow.css";

interface FlowData extends Record<string, unknown> {
  item: WorkflowNode;
  current: boolean;
  expanded: boolean;
  onToggle: (stage: StageId) => void;
}
type FlowNode = Node<FlowData, "workflow">;
function FlowCard({ data, selected }: NodeProps<FlowNode>) {
  const n = data.item;
  return <div className={`wf-node ${n.kind === "stage" ? "wf-stage" : "wf-child"} wf-${n.status} ${selected ? "wf-selected" : ""} ${data.current ? "wf-current" : ""}`}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <div className="wf-node-heading"><span className="wf-node-mark" aria-hidden="true">{statusMark(n.status)}</span><strong>{n.label}</strong></div>
    <div className="wf-node-status">{workflowStatus[n.status] || n.status}{data.current && <b>当前位置</b>}</div>
    {n.kind === "stage" ? <div className="wf-node-bottom"><span>{n.completed} / {n.total} 项完成</span><button type="button" className="nodrag nopan wf-expand" aria-label={`${data.expanded ? "收起" : "展开"}${n.label}`} aria-expanded={data.expanded} onClick={e => { e.stopPropagation(); data.onToggle(n.stage); }}>{data.expanded ? "收起 −" : "展开 ＋"}</button></div>
      : <div className="wf-node-hint">{n.blockers[0] || (n.status === "waiting_return" ? "人工交接 · 等待回传" : n.ready ? "可前往处理" : n.role)}</div>}
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>;
}
const nodeTypes = { workflow: FlowCard };
const outcomeNames: Record<string, string> = { implemented: "已实施归档", not_implemented: "未实施归档", cancelled: "取消归档" };
const effectNames: Record<string, string> = { measured: "效果已实测", pending_observation: "效果观察中" };
function date(value: string) { return new Date(value).toLocaleString("zh-CN", { hour12: false }); }
async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || `读取未完成 (${response.status})`);
  return result as T;
}

export default function WorkflowMap({ projectId, refreshKey, onNavigate, onSnapshot, fontScale = 1 }: {
  projectId: string; refreshKey: unknown; onNavigate: (target: WorkflowAction) => void;
  onSnapshot: (snapshot: WorkflowSnapshot | null) => void;
  fontScale?: number;
}) {
  const [snapshot, setSnapshot] = useState<WorkflowSnapshot | null>(null);
  const [history, setHistory] = useState<WorkflowHistory>({ events: [], next_before_seq: null });
  const [historyError, setHistoryError] = useState(""), [error, setError] = useState("");
  const [loading, setLoading] = useState(true), [moreLoading, setMoreLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(localStorage.getItem(`workflow-collapsed-v2:${projectId}`) !== "false");
  const [fullscreen, setFullscreen] = useState(false);
  const [expanded, setExpanded] = useState<Set<StageId>>(new Set());
  const [selected, setSelected] = useState(localStorage.getItem(`workflow-selected:${projectId}`) || "");
  const [instance, setInstance] = useState<ReactFlowInstance<FlowNode> | null>(null);
  const controller = useRef<AbortController | null>(null), historyController = useRef<AbortController | null>(null);
  const generation = useRef(0), fitted = useRef(false);
  useEffect(() => { fitted.current = false; }, [fontScale]);

  const refresh = useCallback(async () => {
    controller.current?.abort();
    historyController.current?.abort();
    const abort = new AbortController(); controller.current = abort;
    const requestGeneration = ++generation.current;
    setLoading(true); setMoreLoading(false);
    const results = await Promise.allSettled([
      read<WorkflowSnapshot>(`/api/cim/projects/${projectId}/workflow`, abort.signal),
      read<WorkflowHistory>(`/api/cim/projects/${projectId}/audit?limit=20`, abort.signal),
    ]);
    if (requestGeneration !== generation.current || abort.signal.aborted) return;
    const [flow, events] = results;
    if (flow.status === "fulfilled") { setSnapshot(flow.value); onSnapshot(flow.value); setError(""); }
    else { onSnapshot(null); setError(flow.reason instanceof Error ? flow.reason.message : "流程读取失败"); }
    if (events.status === "fulfilled") { setHistory(events.value); setHistoryError(""); }
    else setHistoryError("操作历史未刷新，请重试");
    setLoading(false);
  }, [projectId, onSnapshot]);
  useEffect(() => { void refresh(); return () => { controller.current?.abort(); historyController.current?.abort(); }; }, [refresh, refreshKey]);
  useEffect(() => {
    const focus = () => { void refresh(); };
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [refresh]);
  useEffect(() => {
    if (!snapshot) return;
    if (!snapshot.nodes.some(n => n.id === selected)) setSelected(`stage:${snapshot.current_stage}`);
    else {
      const n = snapshot.nodes.find(n => n.id === selected);
      if (n && n.kind !== "stage") setExpanded(prev => new Set([...prev, n.stage]));
    }
  }, [snapshot, selected]);
  useEffect(() => { if (selected) localStorage.setItem(`workflow-selected:${projectId}`, selected); }, [projectId, selected]);
  useEffect(() => { localStorage.setItem(`workflow-collapsed-v2:${projectId}`, String(collapsed)); }, [projectId, collapsed]);
  useEffect(() => {
    if (!fullscreen) return;
    const previous = document.body.style.overflow; document.body.style.overflow = "hidden";
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    window.addEventListener("keydown", escape);
    const frame = requestAnimationFrame(() => { void instance?.fitView({ padding: 0.12, maxZoom: 0.9 }); });
    return () => { cancelAnimationFrame(frame); document.body.style.overflow = previous; window.removeEventListener("keydown", escape); };
  }, [fullscreen, instance]);
  useEffect(() => {
    if (!instance || !snapshot || fitted.current || collapsed) return;
    const target = snapshot.nodes.find(n => n.id === selected);
    const stage = target?.stage || snapshot.current_stage;
    const column = snapshot.nodes.filter(n => n.kind === "stage").findIndex(n => n.stage === stage);
    const row = snapshot.nodes.filter(n => n.stage === stage && n.kind !== "stage").findIndex(n => n.id === selected);
    const y = target && target.kind !== "stage" ? 239 + Math.max(0, row) * 145 : 100;
    const frame = requestAnimationFrame(() => { void instance.setCenter((column * 268 + 112) * fontScale, y * fontScale, { zoom: 0.85 }); fitted.current = true; });
    return () => cancelAnimationFrame(frame);
  }, [instance, snapshot, collapsed, selected, fontScale]);

  const toggle = useCallback((stage: StageId) => {
    setSelected(`stage:${stage}`);
    setExpanded(prev => {
      const next = new Set(prev); if (next.has(stage)) next.delete(stage); else next.add(stage); return next;
    });
  }, []);
  const graph = useMemo(() => snapshot ? workflowGraph(snapshot, expanded, selected) : null, [snapshot, expanded, selected]);
  const nodes: FlowNode[] = useMemo(() => graph?.visible.map(item => ({
    id: item.id, type: "workflow", position: { x: graph.positions.get(item.id)!.x * fontScale, y: graph.positions.get(item.id)!.y * fontScale },
    data: { item, current: item.kind === "stage" && item.stage === snapshot?.current_stage, expanded: expanded.has(item.stage), onToggle: toggle },
    selected: item.id === selected, width: 224 * fontScale, height: (item.kind === "stage" ? 132 : 118) * fontScale,
    ariaLabel: `${item.label}，${workflowStatus[item.status] || item.status}${item.kind === "stage" && item.stage === snapshot?.current_stage ? "，当前位置" : ""}`,
  })) || [], [graph, snapshot, selected, expanded, toggle, fontScale]);
  const edges = useMemo(() => graph?.edges.map(edge => ({ ...edge,
    type: "smoothstep", className: `wf-edge-${edge.kind}`,
    style: { stroke: edge.kind === "route" ? "#a8b6c0" : "#168779", strokeWidth: edge.kind === "route" ? 1.5 : 2, strokeDasharray: edge.kind === "route" ? "6 5" : undefined },
    label: edge.kind === "route" ? "建议路线" : "前置依赖", labelStyle: { fontSize: 10 * fontScale, fill: "#527080" },
    markerEnd: { type: "arrowclosed" as const, color: edge.kind === "route" ? "#a8b6c0" : "#168779" },
  })) || [], [graph, fontScale]);
  const chosen = snapshot?.nodes.find(n => n.id === selected) || snapshot?.nodes.find(n => n.id === `stage:${snapshot.current_stage}`);
  const select = (id: string) => {
    const n = snapshot?.nodes.find(n => n.id === id); if (!n) return;
    setSelected(id); if (n.kind !== "stage") setExpanded(prev => new Set([...prev, n.stage]));
    const x = (snapshot?.nodes.filter(n => n.kind === "stage").findIndex(s => s.stage === n.stage) || 0) * 268 + 112;
    const row = snapshot?.nodes.filter(child => child.stage === n.stage && child.kind !== "stage").findIndex(child => child.id === n.id) || 0;
    void instance?.setCenter(x * fontScale, (n.kind === "stage" ? 65 : 239 + row * 145) * fontScale, { zoom: 0.85, duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 250 });
  };
  const more = async () => {
    if (!history.next_before_seq || moreLoading) return;
    const cursor = history.next_before_seq, currentGeneration = generation.current;
    const abort = new AbortController(); historyController.current = abort; setMoreLoading(true);
    try {
      const page = await read<WorkflowHistory>(`/api/cim/projects/${projectId}/audit?limit=20&before_seq=${cursor}`, abort.signal);
      if (currentGeneration !== generation.current || abort.signal.aborted) return;
      setHistory(previous => ({ events: [...previous.events, ...page.events.filter(e => !previous.events.some(p => p.seq === e.seq))], next_before_seq: page.next_before_seq }));
      setHistoryError("");
    } catch (e) { if (!abort.signal.aborted) setHistoryError(e instanceof Error ? e.message : "历史加载失败"); }
    finally { if (currentGeneration === generation.current) setMoreLoading(false); }
  };
  const relation = (ids: string[], empty: string) => ids.length ? ids.map(id => {
    const n = snapshot?.nodes.find(n => n.id === id);
    return n ? <button type="button" className="wf-text-button" key={id} onClick={() => select(id)}>{n.label}</button> : null;
  }) : <span className="wf-muted">{empty}</span>;

  return <section className={`wf-map ${fullscreen ? "wf-fullscreen" : ""}`} aria-label="项目流程地图" aria-busy={loading}>
    <div className="wf-heading"><div><span className="fc-eyebrow">PROJECT JOURNEY</span><h3>项目流程地图</h3></div><div className="wf-toolbar">
      {snapshot && <span className="wf-muted">输入 r{snapshot.revision} · {workflowStatus[snapshot.project_status]}</span>}
      <button type="button" className="secondary" disabled={loading} onClick={() => void refresh()}>{loading ? "读取中…" : "刷新流程"}</button>
      <button type="button" className="secondary" onClick={() => { if (collapsed) setCollapsed(false); setFullscreen(!fullscreen); }}>{fullscreen ? "退出全屏" : "全屏查看"}</button>
      <button type="button" className="wf-text-button" aria-expanded={!collapsed} onClick={() => { setCollapsed(!collapsed); setFullscreen(false); }}>{collapsed ? "展开地图" : "收起地图"}</button>
    </div></div>
    {error && <div className="wf-error" role="alert">状态未刷新：{error}。{snapshot ? `当前仍显示 ${date(snapshot.generated_at)} 的快照。` : "请重试读取。"}</div>}
    {!snapshot ? <p className="wf-muted">{loading ? "正在读取项目流程与操作历史…" : "流程暂不可用，现有业务页面仍可使用。"}</p> : <>
      <ol className="wf-stage-strip" aria-label="项目阶段摘要">{snapshot.nodes.filter(n => n.kind === "stage").map((stage, index) => <li key={stage.id} className={`${stage.stage === snapshot.current_stage ? "current" : ""} wf-${stage.status}`}>
        <button type="button" aria-current={stage.stage === snapshot.current_stage ? "step" : undefined} onClick={() => { setCollapsed(false); select(stage.id); }}><span>{String(index + 1).padStart(2, "0")} {stage.label}</span><small>{workflowStatus[stage.status] || stage.status}</small></button>
      </li>)}</ol>
      <div className="wf-summary"><div><span>最近完成</span><strong>{snapshot.recent_completed?.label || "尚无完成记录"}</strong><small>{snapshot.recent_completed ? `${date(snapshot.recent_completed.at)} · ${snapshot.recent_completed.revision == null ? "版本未记录" : `r${snapshot.recent_completed.revision}`}` : "从需求与资料核对开始"}</small></div>
        <div><span>当前待办 · {snapshot.nodes.find(n => n.id === `stage:${snapshot.current_stage}`)?.label}</span><strong>{snapshot.outcome ? outcomeNames[snapshot.outcome.outcome] : `${snapshot.todo.length} 项待处理`}</strong><small>{snapshot.blockers[0] || (snapshot.outcome ? effectNames[snapshot.outcome.effect_status || ""] || snapshot.outcome.reason : "点击节点查看责任、输入与完成条件")}</small></div>
        <div className="wf-recommend"><span>推荐下一步</span><button disabled={!!error || loading} onClick={() => onNavigate(snapshot.recommended)}>{snapshot.recommended.label} ↗</button><small>进入现有页面处理并保存</small></div></div>
      {!collapsed && <>
        <div className="wf-legend"><span><i className="wf-line-dashed" />建议路线</span><span><i className="wf-line-solid" />任务前置依赖</span><span>✓ 已完成</span><span>○ 待处理 / 等待</span><span>! 需处理</span><button className="wf-text-button" onClick={() => select(`stage:${snapshot.current_stage}`)}>定位当前节点</button><button className="wf-text-button" onClick={() => void instance?.fitView({ padding: 0.12, maxZoom: 0.9, duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 250 })}>适应全图</button></div>
        <div className="wf-workspace"><div className="wf-canvas" aria-label="可缩放流程画布">
          <ReactFlow<FlowNode> nodes={nodes} edges={edges} nodeTypes={nodeTypes} onInit={flow => { fitted.current = false; setInstance(flow); }}
            onNodeClick={(_e, n) => setSelected(n.id)} onKeyDown={e => {
              if (e.target instanceof HTMLButtonElement) return;
              const id = (e.target as HTMLElement).closest<HTMLElement>(".react-flow__node")?.dataset.id;
              if (id && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); setSelected(id); }
            }}
            nodesDraggable={false} nodesConnectable={false} edgesFocusable={false} deleteKeyCode={null} minZoom={0.18} maxZoom={1.6}
            defaultViewport={{ x: 20, y: 150, zoom: 0.85 }} proOptions={{ hideAttribution: false }}
            ariaLabelConfig={{ "controls.zoomIn.ariaLabel": "放大流程", "controls.zoomOut.ariaLabel": "缩小流程", "controls.fitView.ariaLabel": "适应全图", "minimap.ariaLabel": "流程缩略图" }}>
            <Background color="#dce6e9" gap={20} /><Controls showInteractive={false} /><MiniMap pannable zoomable nodeColor={n => n.data.current ? "#168779" : "#ccdadd"} />
          </ReactFlow>
        </div><aside className="wf-guide" aria-label="节点使用指引">{chosen && <>
          <span className="fc-eyebrow">{chosen.kind === "stage" ? "阶段指引" : "节点指引"}</span><h3>{chosen.label}</h3>
          <span className={`wf-state wf-${chosen.status}`}>{statusMark(chosen.status)} {workflowStatus[chosen.status] || chosen.status}</span>
          <p>{chosen.purpose}</p><dl><dt>谁来处理</dt><dd>{chosen.role}</dd><dt>所需输入</dt><dd><ul>{chosen.inputs.map((input, i) => <li key={i}>{input}</li>)}</ul></dd>
            <dt>已有成果</dt><dd>{chosen.outputs.length ? chosen.outputs.map((output, i) => <button className="wf-text-button" key={i} onClick={() => onNavigate(output)}>{output.label}</button>) : <span className="wf-muted">当前版本尚无已记录成果</span>}</dd>
            <dt>完成条件</dt><dd>{chosen.completion}</dd><dt>为什么等待</dt><dd>{chosen.blockers.length ? <ul className="wf-warnings">{chosen.blockers.map(b => <li key={b}>{b}</li>)}</ul> : chosen.status === "waiting_return" ? "执行批次已创建，等待厂内处理并回传文件。" : "无额外阻塞；按本步指引处理。"}</dd>
            <dt>上一步 · 前置节点</dt><dd>{relation(chosen.previous, "此节点无前置依赖")}</dd><dt>下一步 · 后续节点</dt><dd>{relation(chosen.next, "此节点无后续依赖")}</dd></dl>
          <button className="wf-go" disabled={!!error || loading} onClick={() => onNavigate(chosen.action)}>{chosen.action.label} ↗</button>
          {chosen.kind === "stage" && <button className="secondary" onClick={() => toggle(chosen.stage)}>{expanded.has(chosen.stage) ? "收起阶段任务" : "展开阶段任务与交接"}</button>}
        </>}</aside></div>
        {snapshot.todo.length > 0 && <div className="wf-todos"><strong>当前阶段全部待办</strong>{snapshot.todo.map(id => {
          const n = snapshot.nodes.find(n => n.id === id)!;
          return <button key={id} className="secondary" onClick={() => select(id)}>{n.label}<small>{workflowStatus[n.status]}</small></button>;
        })}</div>}
        {snapshot.outcome && <p className="wf-outcome">{outcomeNames[snapshot.outcome.outcome]} · {effectNames[snapshot.outcome.effect_status || ""] || "效果状态未记录"} · 归档人 {snapshot.outcome.actor}：{snapshot.outcome.reason}</p>}
        <details className="wf-history"><summary>操作轨迹 · 已载入 {history.events.length} 条{snapshot.historical_tasks > 0 ? ` · ${snapshot.historical_tasks} 个旧版本任务保留在历史中` : ""}</summary>
          <p className="wf-muted">按真实发生顺序倒序展示。返修、补资料及版本变化均保留；历史完成记录不代表当前版本完成。</p>
          {historyError && <p className="wf-error" role="alert">{historyError}</p>}
          <ol>{history.events.map(event => <li key={event.seq}><div><strong>{event.label}</strong><time dateTime={event.at}>{date(event.at)}</time></div><p>{event.actor || "执行人未记录"} · {event.revision == null ? "版本未记录" : `输入 r${event.revision}`}{event.data.stale === true ? " · 过期回传，仅保留历史" : ""}{event.data.decision ? ` · ${String(event.data.decision) === "approve" ? "审查通过" : String(event.data.decision) === "rework" ? "退回返修" : "取消"}` : ""}</p>{event.target && <button className="wf-text-button" onClick={() => onNavigate(event.target!)}>{event.target.label} ↗</button>}</li>)}</ol>
          {!history.events.length && <p className="wf-muted">尚无操作记录</p>}
          {history.next_before_seq && <button className="secondary" disabled={moreLoading || loading} onClick={() => void more()}>{moreLoading ? "加载中…" : "加载更早记录"}</button>}
        </details>
      </>}
    </>}
  </section>;
}
