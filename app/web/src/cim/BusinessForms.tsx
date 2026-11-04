type Obj = Record<string, any>;
type Editor = { value: string; onChange: (text: string) => void };
const asNumber = (text: string) => text === "" ? null : Number(text);
const laborNames: Obj = { investigation: "调查与索资", design: "方案设计", programming: "程序修改", testing: "离线测试", onsite: "现场实施与联调", documentation: "文档归档" };

export function EstimateEditor({ value, onChange }: Editor) {
  const data = JSON.parse(value);
  const put = (patch: Obj) => onChange(JSON.stringify({ ...data, ...patch }, null, 2));
  const bom = (i: number, patch: Obj) => put({ bom: data.bom.map((r: Obj, n: number) => n === i ? { ...r, ...patch } : r) });
  return <>
    <div className="fc-section-title"><h3>BOM 清单</h3><button className="secondary" onClick={() => put({ bom: [...data.bom, { action: "new", spec: "", quantity: 1, unit_price: null, source: "" }] })}>＋ 添加物料</button></div>
    <div className="fc-table-scroll"><table className="fc-edit-table"><thead><tr><th>用途</th><th>规格 / 型号</th><th>数量</th><th>单价 · 未知留空</th><th>报价来源与日期</th><th /></tr></thead><tbody>{data.bom.map((r: Obj, i: number) => <tr key={i}>
      <td><select aria-label={`物料${i + 1}用途`} value={r.action} onChange={e => bom(i, { action: e.target.value })}><option value="new">新购</option><option value="reuse">复用</option><option value="replace">替换</option></select></td>
      <td><input aria-label={`物料${i + 1}规格`} placeholder="实际型号与技术规格" value={r.spec} onChange={e => bom(i, { spec: e.target.value })} /></td>
      <td><input aria-label={`物料${i + 1}数量`} type="number" min="0" step="any" value={r.quantity ?? ""} onChange={e => bom(i, { quantity: asNumber(e.target.value) })} /></td>
      <td><input aria-label={`物料${i + 1}单价`} type="number" min="0" step="any" value={r.unit_price ?? ""} onChange={e => bom(i, { unit_price: asNumber(e.target.value) })} /></td>
      <td><input aria-label={`物料${i + 1}报价来源`} placeholder="供应商、报价单号、日期" value={r.source || ""} onChange={e => bom(i, { source: e.target.value })} /></td>
      <td><button className="fc-link-button" onClick={() => put({ bom: data.bom.filter((_: Obj, n: number) => i !== n) })}>移除</button></td>
    </tr>)}</tbody></table></div>
    <h3 className="fc-form-heading">PLC 修改与实施人天</h3><p className="fc-muted">未评估的工作留空；确认不适用的工作填写 0，并在依据中说明。</p><div className="fc-form-grid">{Object.entries(laborNames).map(([key, label]) => <label className="fc-field" key={key}><span>{String(label)}（人天）</span><input aria-label={String(label) + "人天"} type="number" min="0" step="0.25" placeholder="待评估" value={data.labor[key] ?? ""} onChange={e => put({ labor: { ...data.labor, [key]: asNumber(e.target.value) } })} /></label>)}<label className="fc-field"><span>人天费率 · 未知留空</span><input aria-label="人天费率" type="number" min="0" step="any" value={data.daily_rate ?? ""} onChange={e => put({ daily_rate: asNumber(e.target.value) })} /></label></div>
    <h3 className="fc-form-heading">收益与判断依据</h3><div className="fc-form-grid"><label className="fc-field"><span>收益性质</span><select aria-label="收益性质" value={data.benefit.kind} onChange={e => put({ benefit: { ...data.benefit, kind: e.target.value, ...(e.target.value === "nonmonetary" ? { annual_value: null } : {}) } })}><option value="estimated">预计收益</option><option value="measured">实测收益 · 仍须附验收证据</option><option value="nonmonetary">非货币收益</option></select></label><label className="fc-field"><span>年度金额 · 同一币种，未知留空</span><input aria-label="年度收益金额" type="number" min="0" step="any" disabled={data.benefit.kind === "nonmonetary"} value={data.benefit.annual_value ?? ""} onChange={e => put({ benefit: { ...data.benefit, annual_value: asNumber(e.target.value) } })} /></label></div>
    <label className="fc-field"><span>收益公式、币种、数据来源和统计窗口</span><textarea aria-label="收益计算依据" rows={3} value={data.benefit.basis} onChange={e => put({ benefit: { ...data.benefit, basis: e.target.value } })} /></label><label className="fc-field"><span>估算假设、停线安排和未计入项目 · 每行一项</span><textarea aria-label="估算假设" rows={3} value={data.assumptions.join("\n")} onChange={e => put({ assumptions: e.target.value.split("\n") })} /></label>
  </>;
}

export function ArchiveEditor({ value, onChange, documents }: Editor & { documents: Obj[] }) {
  const data = JSON.parse(value);
  const put = (patch: Obj) => onChange(JSON.stringify({ ...data, ...patch }, null, 2));
  const comparison = { baseline: "", after: "", metric_definition: "", product_recipe: "", window: "", effect_status: "pending_observation", confounders: [], source_ids: [], ...data.comparison };
  const change = (patch: Obj) => put({ comparison: { ...comparison, ...patch } });
  return <><div className="fc-form-grid"><label className="fc-field"><span>项目结局</span><select aria-label="项目结局" value={data.outcome} onChange={e => put({ outcome: e.target.value })}><option value="not_implemented">未实施</option><option value="implemented">已实施</option><option value="cancelled">已取消</option></select></label><label className="fc-field"><span>归档责任人</span><input aria-label="归档责任人" value={data.actor} onChange={e => put({ actor: e.target.value })} /></label></div>
    <label className="fc-field"><span>实施结论 / 未实施或取消原因</span><textarea aria-label="归档原因" rows={3} value={data.reason} onChange={e => put({ reason: e.target.value })} /></label>
    {data.outcome === "implemented" && <><h3 className="fc-form-heading">改造前后对照</h3><div className="fc-form-grid"><label className="fc-field"><span>效益观察状态</span><select aria-label="效益观察状态" value={comparison.effect_status} onChange={e => change({ effect_status: e.target.value })}><option value="pending_observation">工程交付完成 · 效果观察中</option><option value="measured">效果已有实测记录</option></select></label>{[["metric_definition", "指标及计算口径"], ["product_recipe", "产品与配方"], ["window", "改前 / 改后的统计窗口"]].map(([key, label]) => <label className="fc-field" key={key}><span>{label}</span><input aria-label={label} value={comparison[key]} onChange={e => change({ [key]: e.target.value })} /></label>)}</div><div className="fc-two-col">{[["baseline", "改前基线与来源"], ["after", "改后结果 / 待观察事项"]].map(([key, label]) => <label className="fc-field" key={key}><span>{label}</span><textarea aria-label={label} rows={4} value={comparison[key]} onChange={e => change({ [key]: e.target.value })} /></label>)}</div>
      <label className="fc-field"><span>产品结构、良率、班次等混杂因素 · 每行一项</span><textarea aria-label="混杂因素" rows={2} value={comparison.confounders.join("\n")} onChange={e => change({ confounders: e.target.value.split("\n") })} /></label><fieldset className="fc-evidence-picker"><legend>前后对照原始资料</legend>{documents.length ? documents.map(d => <label key={d.id}><input type="checkbox" checked={comparison.source_ids.includes(d.id)} onChange={e => change({ source_ids: e.target.checked ? [...comparison.source_ids, d.id] : comparison.source_ids.filter((id: string) => id !== d.id) })} />{d.name}</label>) : <p className="fc-muted">先在资料入口添加原始记录。</p>}</fieldset></>}
    <label className="fc-field"><span>实际投入 · 物料、工时、停线、币种与依据</span><textarea aria-label="实际投入" rows={3} value={data.actual_investment.notes || ""} onChange={e => put({ actual_investment: { ...data.actual_investment, notes: e.target.value } })} /></label><label className="fc-field"><span>遗留事项 / 观察计划 · 每行一项</span><textarea aria-label="遗留事项" rows={3} value={data.remaining.join("\n")} onChange={e => put({ remaining: e.target.value.split("\n") })} /></label>
  </>;
}
