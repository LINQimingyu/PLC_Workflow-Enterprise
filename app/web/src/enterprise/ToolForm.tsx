import {useState} from "react";
type Row=Record<string,any>;
type Props={run:Row,busy:boolean,submit:(body:Row)=>Promise<unknown>};
const names:Row={"electrical.calculate":"负载电流计算","energy.calculate":"单位合格品能耗","diagnosis.check":"故障上下文核查","plc.inspect_csv":"PLC CSV 静态解析","plc.compare_csv":"PLC CSV 差异","tt.analyze":"TT 日志质量与瓶颈分析","vendor.compile":"厂商编译边界检查","vendor.simulate":"厂商仿真边界检查"};
const defaults:Row={
 "electrical.calculate":{power_kw:null,voltage_v:null,power_factor:null,efficiency:null,phases:null},
 "energy.calculate":{period:"",boundary:"",energy_kwh:null,good_units:null,operating_states:[],quality:"",tariff:""},
 "diagnosis.check":{device:"",time:"",alarm:"",before_state:"",after_state:"",recent_operations:"",safety_conditions:""},
 "plc.inspect_csv":{source_id:"",cpu:""},"plc.compare_csv":{before_id:"",after_id:""},
 "tt.analyze":{source_id:"",terminal_station:"",window_start:"",window_end:"",synthetic:false},
 "vendor.compile":{},"vendor.simulate":{}
};
export default function ToolForm({run,busy,submit}:Props){
 const [tool,setTool]=useState(run.contract.tools[0]||"");
 const [args,setArgs]=useState(JSON.stringify(defaults[tool]||{},null,2));
 const [result,setResult]=useState<Row|null>(null),[error,setError]=useState("");
 if(!run.contract.tools.length)return null;
 return <details><summary>受控计算与解析工具</summary><p>只执行合同内工具，结果为分析或计算；厂商验证需创建独立工具任务。</p><form className="ep-form" onSubmit={async e=>{e.preventDefault();setError("");try{setResult(await submit({key:crypto.randomUUID(),name:tool,args:JSON.parse(args)}) as Row);}catch(err){setError(String(err));}}}><fieldset disabled={busy}>
 <label>本任务工具<select aria-label="本任务工具" value={tool} onChange={e=>{setTool(e.target.value);setArgs(JSON.stringify(defaults[e.target.value]||{},null,2));}}>{run.contract.tools.map((t:string)=><option value={t} key={t}>{names[t]||t}</option>)}</select></label>
 <label>计算与解析参数<textarea aria-label="计算与解析参数" rows={8} value={args} onChange={e=>setArgs(e.target.value)}/><small>输入文件 ID 只能取自本任务合同。功率 kW，电压 V，电耗 kWh；未知参数返回缺项。</small></label>
 <button type="submit">执行受控工具</button>{error&&<p role="alert" className="ep-error">{error}</p>}</fieldset></form>{result&&<pre aria-label="工具计算结果">{JSON.stringify(result,null,2)}</pre>}</details>;
}
