import { workflowStatus, type WorkflowSnapshot } from "./workflow-model";
type Obj = Record<string, any>;
const phases = [["static", "静态检查"], ["compile", "GX 编译"], ["simulation", "模拟验证"], ["field", "现场验证"], ["benefit", "效果对照"]];
export default function VerificationOverview({ records, revision, snapshot, onSelect }: {
  records: Obj[]; revision: number; snapshot: WorkflowSnapshot | null; onSelect: (phase: string) => void;
}) {
  return <section className="fc-surface fc-verification-overview" aria-label="当前版本验证证据">
    <div className="fc-section-title"><h2>验证证据一览</h2><span className="fc-muted">当前输入 r{revision}</span></div>
    <p className="fc-muted">各项按当前版本最新登记结果显示；效果对照独立观察，归档不等于验证通过。</p>
    <div className="fc-evidence-list">{phases.map(([id, label]) => {
      const record = records.filter(r => r.revision === revision && r.phase === id).at(-1);
      const node = snapshot?.revision === revision ? snapshot.nodes.find(n => n.id === `verification:${id}`) : undefined;
      const status = node?.status || "unknown";
      return <div key={id} className="fc-evidence-row"><strong>{label}</strong><span className={`fc-badge ${status}`}>{workflowStatus[status] || "状态待刷新"}</span><div><span>{record ? `登记人：${record.actor || "未记录"}` : "尚无当前版本记录"}</span><small>{record?.record || "登记步骤、预期、实际与证据来源。"}</small></div><button type="button" className="secondary" onClick={() => onSelect(id)}>查看 / 登记{label}</button></div>;
    })}</div>
  </section>;
}
