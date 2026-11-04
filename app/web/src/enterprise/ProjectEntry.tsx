import {FolderKanban,Layers,Files,FlaskConical,ShieldCheck,PackageCheck,BookOpen,Users,Plus} from "lucide-react";

export const pageInfo = {
 overview:{title:"项目总控",heading:"从一个离线工程项目开始",summary:"受理项目、确认需求与工具链，再按模块组织交付。",icon:FolderKanban,steps:[["明确输入","设备、CPU、工具链、需求与原件摘要。"],["安排工作","确定模块、责任岗位、授权和独立审核人。"],["跟踪交付","门禁、风险与工程发布分别记录。"]]},
 modules:{title:"工作模块",heading:"按工作模块组织任务",summary:"查看模块职责，选择项目后建立合同、安排执行与独立审核。",icon:Layers,steps:[["明确交付","只拆分需要独立交付和独立审核的工作。"],["选择执行方式","人工、厂内 Agent 任务包或已批准模型 API。"],["核对合同","输入、Skill、工具、预算和停止条件绑定到任务。"]]},
 artifacts:{title:"工程制品",heading:"管理原件与工程制品版本",summary:"选择项目后导入原件、需求、方案及候选文件，保留来源与摘要。",icon:Files,steps:[["保留原件","导入文件并注明来源、分级与用途。"],["建立版本","同一制品的修订生成新版本，历史文件保留。"],["追溯依据","候选、测试和发布清单关联精确文件及摘要。"]]},
 validation:{title:"工具与修复",heading:"验证证据与补丁修复",summary:"选择项目后登记验证记录、创建厂商工具任务，或处理编译失败后的补丁。",icon:FlaskConical,steps:[["分层验证","静态、编译、仿真、现场和效果分别记录。"],["逐轮补丁","失败证据 → 补丁建议 → 人工确认 → 隔离新版本 → 重编译。"],["人工接管","连续三轮程序修复失败即停止；工具环境故障另计。"]]},
 risks:{title:"工程审查",heading:"工程审查与风险处置",summary:"选择项目后审查程序、电气与工艺影响，记录风险、整改及关闭依据。",icon:ShieldCheck,steps:[["登记风险","标明严重程度、问题、整改与回退条件。"],["独立处置","风险提出者不能自行关闭或豁免。"],["发布门禁","严重与高风险必须关闭，未处置风险阻止发布。"]]},
 release:{title:"工程交付",heading:"工程发布与实施交接",summary:"选择项目后核对门禁与精确工程版本，生成锁定包并记录后续交接。",icon:PackageCheck,steps:[["锁定工程包","需求、方案、工具链、验证、风险和终审绑定成清单。"],["导出重验","导出时重新核对摘要、权限和批准是否有效。"],["分别交接","工程包发布、人工实施、现场接受与效果观察独立记录。"]]},
 knowledge:{title:"知识治理",heading:"个人参考与生产知识治理",summary:"选择项目后，按权限及适用性检索知识、提取候选，并审核发布或撤回。",icon:BookOpen,steps:[["个人参考","经本人接受后参考复用，保留验证深度与适用边界。"],["生产知识","脱敏、领域审核、样板回归与两名不同实名审核人批准。"],["撤回追踪","停止后续使用并定位受影响的任务和项目。"]]},
 settings:{title:"岗位与设置",heading:"全局设置与项目岗位",summary:"实名用户与厂内模型属于全局设置；项目岗位和总控方式在选择项目后设置。",icon:Users,steps:[["全局账号","管理员可在下方创建实名用户，无需先建项目。"],["全局模型","管理员可配置厂内模型连接并执行合成探针。"],["项目岗位","选择项目后，分配成员、责任岗位与总控方式。"]]}
} as const;

export function pageFor(tab:string){return pageInfo[tab as keyof typeof pageInfo]||pageInfo.overview;}

export default function ProjectEntry({tab,projects,busy,onSelect,onCreate}:{
 tab:string;projects:{id:string,name:string}[];busy:boolean;onSelect:(id:string)=>void;onCreate:()=>void;
}){
 const page=pageFor(tab),Icon=page.icon;
 return <section className="ep-project-entry" aria-label={page.title+"入口"}>
 <div className="ep-card ep-entry-intro">
 <div className="ep-entry-heading"><Icon size={26} aria-hidden="true"/><h2>{page.heading}</h2></div>
 <p className="ep-entry-context">{tab==="settings"?"全局账号与模型设置可在下方使用；项目岗位需先选择项目。":projects.length?"请选择项目，进入"+page.title+"操作区。":"暂无可访问的项目，可先新建项目；已有项目的访问权限由负责人分配。"}</p>
 <div className="ep-entry-picker">
 {projects.length>0&&<label>选择要处理的项目<select aria-label="选择要处理的项目" value="" disabled={busy} onChange={e=>{if(e.target.value)onSelect(e.target.value);}}><option value="">请选择项目</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
 {tab!=="settings"&&<button className="ep-primary" disabled={busy} onClick={onCreate}><Plus size={16} aria-hidden="true"/>新建项目</button>}
 </div>
 <details className="ep-entry-help"><summary>查看{page.title}操作说明</summary><ol>{page.steps.map(([title,description])=><li key={title}><strong>{title}</strong><span>{description}</span></li>)}</ol></details>
 </div>
 </section>;
}
