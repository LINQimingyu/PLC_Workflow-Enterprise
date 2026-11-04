import {useEffect,useState} from "react";
import type {FormEvent} from "react";
type Row=Record<string,any>;
type Props={admin:boolean,api:(path:string,body?:Row)=>Promise<any>,onOpenSettings:()=>void};
const names:Row={agent:"Agent",skill:"Skill",tool:"工具",bindings:"模块绑定"};

export default function MaintenancePanel({admin,api,onOpenSettings}:Props){
 const [catalog,setCatalog]=useState<Row|null>(null),[kind,setKind]=useState("agent"),[query,setQuery]=useState(""),[filter,setFilter]=useState("");
 const [detail,setDetail]=useState<Row|null>(null),[editor,setEditor]=useState<Row|null>(null),[note,setNote]=useState("");
 const [busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");
 const [bindingModule,setBindingModule]=useState("control"),[binding,setBinding]=useState<Row|null>(null);
 async function reload(){const result=await api("/maintenance");setCatalog(result);return result;}
 useEffect(()=>{if(admin)void reload().catch(e=>setError(String(e.message)));},[admin]);
 useEffect(()=>{if(catalog)setBinding({...catalog.bindings.find((b:Row)=>b.module===bindingModule),note:""});},[catalog,bindingModule]);
 async function action(call:()=>Promise<any>,success:string){if(busy)return;setBusy(true);setError("");setMessage("");try{const result=await call();await reload();setMessage(success);return result;}catch(e){setError(e instanceof Error?e.message:String(e));return null;}finally{setBusy(false);}}
 async function show(id:string){await action(async()=>{setDetail(await api("/maintenance/versions/"+id));setEditor(null);setNote("");},"已读取版本");}
 function start(source?:Row,edit=false){setError("");setMessage("");setEditor(source?{...source.payload,kind:source.kind,key:source.key,source,edit,note:""}:{kind,key:"",name:"",modules:[],instructions:"",implementation:"",note:""});}
 async function save(e:FormEvent){e.preventDefault();if(!editor)return;const fields={name:editor.name,modules:editor.modules,instructions:editor.instructions,implementation:editor.implementation,note:editor.note};
  const result=await action(()=>editor.edit?api("/maintenance/versions/"+editor.source.id+"/edit",{...fields,expected_sha:editor.source.sha256}):api("/maintenance/versions",{...fields,kind:editor.kind,key:editor.key,...(editor.source?{base_id:editor.source.id,expected_sha:editor.source.sha256}:{})}),"草稿已保存；尚未发布或绑定");
  if(result){setDetail(await api("/maintenance/versions/"+result.id));setEditor(null);setNote("");}
 }
 async function lifecycle(actionName:string){if(!detail)return;const result=await action(()=>api("/maintenance/versions/"+detail.id+"/"+actionName,actionName==="publish"?{expected_sha:detail.sha256,note}:{enabled:!detail.enabled,note}),actionName==="publish"?"版本已发布，可以显式绑定到模块":"启停状态已更新");if(result){setDetail(await api("/maintenance/versions/"+detail.id));setNote("");}}
 if(!admin)return <section className="ep-card"><h2>Agent、Skill 与工具维护</h2><p>由系统管理员维护全局版本与模块绑定。任务中使用的版本快照可在所属模块合同查看。</p></section>;
 const modules:Row[]=catalog?.modules||[],items:Row[]=catalog?.items||[];
 const filtered=items.filter(v=>v.kind===kind&&(!filter||v.modules.includes(filter))&&(!query||[v.name,v.key,v.id].join(" ").toLowerCase().includes(query.toLowerCase())));
 const optionsFor=(type:string)=>items.filter(v=>v.kind===type&&v.modules.includes(bindingModule)&&v.status==="published");
 const applicable=modules.filter(m=>editor?.modules.includes(m.id));
 const implementationTools:string[]=applicable.length?applicable[0].tools.filter((tool:string)=>applicable.every(m=>m.tools.includes(tool))):[];
 return <section className="ep-card ep-maintenance">
  <div className="ep-section-head"><div><h2>维护目录与版本</h2><p>管理模块 Agent 配置、Skill 方法及已准入工具；执行权限仍由项目合同控制。</p></div><div className="ep-actions"><button disabled={busy} onClick={onOpenSettings}>模型连接设置</button><button disabled={busy} onClick={()=>void action(reload,"目录已刷新")}>刷新维护目录</button></div></div>
  <div className="ep-maint-tabs" role="tablist" aria-label="维护类型">{Object.entries(names).map(([key,label])=><button role="tab" aria-selected={kind===key} key={key} disabled={busy} onClick={()=>{setKind(key);setDetail(null);setEditor(null);setError("");setMessage("");}}>{String(label)}</button>)}</div>
  {error&&<p className="ep-error" role="alert">{error}</p>}{message&&<p className="ep-note" role="status">{message}</p>}
  {!catalog?<p>正在读取维护目录…</p>:kind==="bindings"&&binding?<form className="ep-form" onSubmit={async e=>{e.preventDefault();await action(()=>api("/maintenance/bindings/"+bindingModule,{agent_id:binding.agent_id,skill_id:binding.skill_id,tool_ids:binding.tool_ids,expected_revision:binding.revision,note:binding.note}),"模块绑定已保存，仅影响新建任务；已有合同快照保留");}}><fieldset disabled={busy}>
   <label>绑定工作模块<select aria-label="绑定工作模块" value={bindingModule} onChange={e=>setBindingModule(e.target.value)}>{modules.map(m=><option value={m.id} key={m.id}>{m.name}</option>)}</select></label>
   <label>绑定 Agent 版本<select aria-label="绑定 Agent 版本" value={binding.agent_id} onChange={e=>setBinding({...binding,agent_id:e.target.value})}>{optionsFor('agent').map(v=><option disabled={!v.enabled} key={v.id} value={v.id}>{v.name} · v{v.version}{v.enabled?"":"（已停用）"}</option>)}</select></label>
   <label>绑定 Skill 版本<select aria-label="绑定 Skill 版本" value={binding.skill_id} onChange={e=>setBinding({...binding,skill_id:e.target.value})}>{optionsFor('skill').map(v=><option disabled={!v.enabled} key={v.id} value={v.id}>{v.name} · v{v.version}{v.enabled?"":"（已停用）"}</option>)}</select></label>
   <label>绑定工具版本<select aria-label="绑定工具版本" multiple value={binding.tool_ids} onChange={e=>setBinding({...binding,tool_ids:Array.from(e.target.selectedOptions,o=>o.value)})}>{optionsFor('tool').map(v=><option disabled={!v.enabled} key={v.id} value={v.id}>{v.name} · v{v.version} · {v.implementation}{v.enabled?"":"（已停用）"}</option>)}</select><small>可不绑定工具；任务仍需单独选择并获授权。</small></label>
   <label>绑定依据<textarea aria-label="绑定依据" required value={binding.note} onChange={e=>setBinding({...binding,note:e.target.value})}/></label><button className="ep-primary" type="submit">保存模块绑定</button>
  </fieldset></form>:<>
   <div className="ep-maint-filter"><label>搜索维护目录<input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="名称或标识"/></label><label>适用模块筛选<select aria-label="适用模块筛选" value={filter} onChange={e=>setFilter(e.target.value)}><option value="">全部模块</option>{modules.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label><button className="ep-primary" disabled={busy} onClick={()=>{setDetail(null);start();}}>新增{names[kind]}</button></div>
   <div className="ep-table-wrap"><table><thead><tr><th>名称与标识</th><th>版本／来源</th><th>状态</th><th>适用模块</th><th>维护</th></tr></thead><tbody>{filtered.map(v=><tr key={v.id}><td><strong>{v.name}</strong><small>{v.key}</small></td><td>v{v.version} · {v.builtin?"内置基线":"维护版本"}</td><td>{v.status==="draft"?"草稿":v.enabled?"已发布 · 启用":"已发布 · 停用"}</td><td>{v.modules.map((id:string)=>modules.find(m=>m.id===id)?.name||id).join("、")}</td><td><button disabled={busy} onClick={()=>void show(v.id)} aria-label={"查看 "+v.name+" v"+v.version}>查看</button></td></tr>)}</tbody></table>{!filtered.length&&<p>暂无符合条件的版本，可新增草稿。</p>}</div>
   {editor?<div className="ep-maint-detail"><h3>{editor.edit?"编辑草稿":editor.source?"派生新版本":"新增"+names[editor.kind]+"草稿"}</h3><form className="ep-form" onSubmit={save}><fieldset disabled={busy}>
    <label>能力标识<input required pattern="[a-z][a-z0-9._-]{1,79}" disabled={!!editor.source} value={editor.key} onChange={e=>setEditor({...editor,key:e.target.value})}/></label><label>能力名称<input required maxLength={100} value={editor.name} onChange={e=>setEditor({...editor,name:e.target.value})}/></label>
    <label>适用工作模块<select aria-label="适用工作模块" multiple required value={editor.modules} onChange={e=>setEditor({...editor,modules:Array.from(e.target.selectedOptions,o=>o.value),implementation:""})}>{modules.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
    {editor.kind==="tool"&&<label>工具实现<select aria-label="工具实现" required value={editor.implementation} onChange={e=>setEditor({...editor,implementation:e.target.value})}><option value="">请选择已准入实现</option>{implementationTools.map(t=><option key={t} value={t}>{t}</option>)}</select></label>}
    <label>{editor.kind==="agent"?"Agent 职责与指令":editor.kind==="skill"?"Skill 方法内容":"工具使用说明"}<textarea aria-label={editor.kind==="agent"?"Agent 职责与指令":editor.kind==="skill"?"Skill 方法内容":"工具使用说明"} required rows={10} maxLength={50000} value={editor.instructions} onChange={e=>setEditor({...editor,instructions:e.target.value})}/></label>
    <label>维护原因<textarea aria-label="维护原因" required value={editor.note} onChange={e=>setEditor({...editor,note:e.target.value})}/></label><button className="ep-primary" type="submit">保存草稿</button><button type="button" onClick={()=>setEditor(null)}>取消编辑</button>
   </fieldset></form></div>:detail&&<div className="ep-maint-detail"><h3>版本详情：{detail.payload.name} · v{detail.version}</h3><p>{detail.builtin?"内置基线":"维护版本"} · {detail.status==="draft"?"草稿":detail.enabled?"已发布／启用":"已发布／停用"}</p><code>{detail.sha256}</code><pre>{detail.payload.instructions}</pre>
    <div className="ep-actions">{detail.status==="draft"&&<button disabled={busy} onClick={()=>start(detail,true)}>编辑草稿</button>}<button disabled={busy} onClick={()=>start(detail)}>编辑为新版本</button></div>
    <label className="ep-maint-reason">发布／启停依据<textarea aria-label="发布／启停依据" value={note} onChange={e=>setNote(e.target.value)}/></label><div className="ep-actions">{detail.status==="draft"?<button disabled={busy||!note.trim()} onClick={()=>void lifecycle('publish')}>发布此版本</button>:<button disabled={busy||!note.trim()} onClick={()=>void lifecycle('enable')}>{detail.enabled?"停用此版本":"启用此版本"}</button>}</div>
    <details><summary>版本历史（{detail.history.length}）</summary><ul>{detail.history.map((v:Row)=><li key={v.id}><button disabled={busy} onClick={()=>void show(v.id)}>查看 v{v.version} · {v.status==="draft"?"草稿":"已发布"}</button></li>)}</ul></details>
    <details><summary>维护记录（{detail.events?.length||0}）</summary>{detail.events?.map((event:Row)=><p key={event.seq}>{event.action} · {event.actor}<br/>{event.data.note}</p>)}</details>
   </div>}
  </>}
  <details className="ep-maint-help"><summary>维护与执行的关系</summary><p>发布配置不等于授权任务或批准工程。模块绑定只影响新建任务，已有合同保留 Agent、Skill 与工具版本快照。停用版本会阻止依赖它的后续执行；模型或工具已经发出的请求不能被撤销，迟到结果保留审计。</p><p>内置 Agent 是各模块的可选配置基线，不表示必须创建固定数量的 Agent。上游专业角色仍按任务场景路由。模型连接在“岗位与设置”维护，任务授权前另行绑定已通过探针的模型。工具新增配置只映射平台已准入实现；新程序或厂商适配器需通过代码集成与验证准入。</p></details>
 </section>;
}
