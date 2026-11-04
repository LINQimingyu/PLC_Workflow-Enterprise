export type WorkflowTab = "overview" | "documents" | "tasks" | "analysis" | "business" | "delivery";
export type StageId = "requirements" | "baseline" | "analysis" | "proposal" | "review" | "verification" | "archive";
export interface WorkflowAction {
  label: string;
  tab: WorkflowTab;
  task_id?: string;
  document_id?: string;
  record_id?: string;
  phase?: string;
  focus?: string;
}
export interface WorkflowNode {
  id: string;
  kind: "stage" | "task" | "step" | "verification";
  stage: StageId;
  label: string;
  status: string;
  role: string;
  purpose: string;
  inputs: string[];
  outputs: WorkflowAction[];
  completion: string;
  blockers: string[];
  previous: string[];
  next: string[];
  action: WorkflowAction;
  completed?: number;
  total?: number;
  ready?: boolean;
}
export interface WorkflowEdge { id: string; source: string; target: string; kind: "route" | "dependency" }
export interface WorkflowEvent {
  seq: number;
  at: string;
  action: string;
  label: string;
  actor: string | null;
  revision: number | null;
  target: WorkflowAction | null;
  data: Record<string, unknown>;
}
export interface WorkflowSnapshot {
  project_id: string;
  revision: number;
  project_status: string;
  generated_at: string;
  current_stage: StageId;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  blockers: string[];
  todo: string[];
  recommended: WorkflowAction;
  recent_completed: WorkflowEvent | null;
  outcome: { outcome: string; effect_status: string | null; reason: string; actor: string } | null;
  historical_tasks: number;
}
export interface WorkflowHistory { events: WorkflowEvent[]; next_before_seq: number | null }
export const workflowStatus: Record<string, string> = {
  completed: "已完成", queued: "待执行", waiting_return: "等待厂内回传", review: "待人工审查",
  approved: "已审查通过", needs_info: "待补充", rework: "返修", failed: "失败",
  stale: "输入或证据已过期", cancelled: "已取消", not_run: "未验证", passed: "通过 · 已登记证据",
  not_applicable: "有理由豁免", paused: "已暂停", active: "进行中", archived: "已归档",
};
export function statusMark(status: string): string {
  if (["completed", "approved", "passed"].includes(status)) return "✓";
  if (["failed", "rework", "stale", "needs_info"].includes(status)) return "!";
  if (status === "cancelled") return "×";
  if (status === "not_applicable") return "−";
  return "○";
}

/** Fixed columns preserve spatial memory; relation lines are focused on selection. */
export function workflowGraph(snapshot: WorkflowSnapshot, expanded: ReadonlySet<StageId>, selected: string) {
  const stages = snapshot.nodes.filter(n => n.kind === "stage");
  const visible = snapshot.nodes.filter(n => n.kind === "stage" || expanded.has(n.stage));
  const positions = new Map<string, { x: number; y: number }>();
  stages.forEach((stage, column) => {
    positions.set(stage.id, { x: column * 268, y: 0 });
    visible.filter(n => n.stage === stage.stage && n.kind !== "stage").forEach((n, row) => {
      positions.set(n.id, { x: column * 268, y: 180 + row * 145 });
    });
  });
  const lookup = new Map(snapshot.nodes.map(n => [n.id, n]));
  const edgeMap = new Map<string, WorkflowEdge>();
  snapshot.edges.forEach(edge => {
    if (edge.kind === "route") { edgeMap.set(edge.id, edge); return; }
    const focused = selected.startsWith("task:");
    if (focused && edge.source !== selected && edge.target !== selected) return;
    if (!focused && (!positions.has(edge.source) || !positions.has(edge.target))) return;
    const source = positions.has(edge.source) ? edge.source : `stage:${lookup.get(edge.source)?.stage}`;
    const target = positions.has(edge.target) ? edge.target : `stage:${lookup.get(edge.target)?.stage}`;
    if (source === target || !positions.has(source) || !positions.has(target)) return;
    const key = `dependency:${source}:${target}`;
    edgeMap.set(key, { ...edge, id: key, source, target });
  });
  return { visible, positions, edges: [...edgeMap.values()] };
}
