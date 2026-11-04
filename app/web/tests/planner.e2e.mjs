/** Isolated browser workflow with an injected fake model and in-memory keys. */
import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const app=resolve(dirname(fileURLToPath(import.meta.url)),"../..");
const qa=resolve(app,".qa"), origin="http://127.0.0.1:18774", token="planner-browser-fixture-only";
await mkdir(resolve(qa,"screenshots"),{recursive:true});
const helper=resolve(qa,"planner-browser-server.py");
await writeFile(helper, String.raw`
import json,os
from pathlib import Path
import uvicorn
from integrations.web.app import create_app
from cim.workbench import FactoryWorkbench
root=Path(__file__).resolve().parent/'planner-browser-workspace'
os.environ['PLC_AI_DATA_DIR']=str(root/'.local/settings')
os.environ['DO_NOT_TRACK']='1'
service=FactoryWorkbench(root/'engineering',root/'engineering-state')
app=create_app(root/'engineering',service=service,origin='${origin}',operator_token='${token}')
class Secrets:
 def __init__(self):self.values={}
 def read(self,target):return self.values.get(target,'')
 def write(self,target,value):self.values[target]=value
 def delete(self,target):self.values.pop(target,None)
app.state.factory.planner.secrets=Secrets()
count=0
def complete(settings,key,messages):
 global count
 count+=1
 (root.parent/'planner-model-calls.json').write_text(json.dumps({'calls':count}),encoding='utf-8')
 cpu='Q26UDV' if 'Q26UDV' in messages[-1]['content'] else None
 return json.dumps({'summary':'仅供浏览器验收的合成规划，非现场事实确认','fields':{'name':'Agent 创建验收示例','scenario':'fdc','area':'FA','cpu':cpu,'equipment':'LUL Conveyor','requirements':'仅一台搬送机马达负载上报；点表与现场验收值待确认'},'questions':[] if cpu else ['请确认 CPU 型号'],'agent_ids':['cim-fdc','fa-glass'],'pack_ids':['fa-starter']},ensure_ascii=False)
app.state.factory.planner.transport=complete
(root.parent/'planner-model-calls.json').write_text(json.dumps({'calls':0}),encoding='utf-8')
uvicorn.run(app,host='127.0.0.1',port=18774,access_log=False)
`,"utf8");
const server=spawn(resolve(app,"../.venv/Scripts/python.exe"),[helper],{cwd:app,env:{...process.env,PYTHONPATH:resolve(app,"src"),PYTHONUTF8:"1"},windowsHide:true,stdio:["ignore","ignore","pipe"]});
let log="",browser,page; const tests=[],errors=[];
server.stderr.on("data",d=>{log+=d;});
async function check(name,fn){await fn();tests.push(name);}
async function calls(){return JSON.parse(await readFile(resolve(qa,"planner-model-calls.json"),"utf8")).calls;}
try{
 for(let n=0;n<100;n++){
  try{if((await fetch(origin+"/api/health")).ok)break;}catch{}
  if(server.exitCode!==null)throw new Error(log);
  if(n===99)throw new Error("Planner browser server timed out");
  await new Promise(r=>setTimeout(r,150));
 }
 browser=await chromium.launch({channel:"msedge",headless:true});
 page=await browser.newPage({viewport:{width:1440,height:1050}});page.on("pageerror",e=>errors.push(String(e)));
 await page.goto(origin+"/#cim");
 await page.getByLabel("操作员凭证",{exact:true}).fill(token);
 await page.getByRole("button",{name:"进入工作台",exact:true}).click();
 await page.getByRole("button",{name:"＋ 新建项目",exact:true}).waitFor();
 await check("workspace workflow entry explains seven complete stages and actual pack maturity",async()=>{
  await page.getByRole("button",{name:"工作流",exact:true}).click();
  await page.getByRole("heading",{name:"从需求到归档，每一步怎么做",exact:true}).waitFor();
  assert.equal(await page.locator(".wg-route button").count(),7);
  await page.getByRole("button",{name:"展开全部步骤",exact:true}).click();
  assert.equal(await page.locator("[data-guide-stage]").count(),7);
  assert.equal(await page.locator(".wg-pack").count(),4);
  assert.match(await page.locator(".wg-pack").first().innerText(),/约束 0/);
  await page.locator(".wg-route button").filter({hasText:"专业分析"}).click();
  assert.equal(await page.locator("[data-guide-stage]").count(),1);
  assert.match(await page.locator("[data-guide-stage]").innerText(),/下载 ZIP/);
  await page.screenshot({path:resolve(qa,"screenshots/workflow-guide.png"),fullPage:true});
 });
 await check("missing planner key stays actionable without a model call",async()=>{
  await page.getByRole("button",{name:"由项目规划 Agent 协助创建",exact:true}).click();
  await page.getByLabel("项目规划描述",{exact:true}).fill("FA 搬送机要增加马达负载上报，请先帮我梳理整体流程。");
  await page.getByLabel("规划描述分级",{exact:true}).selectOption("public");
  await page.getByRole("button",{name:"让 Agent 梳理需求",exact:true}).click();
  await page.getByRole("alert").filter({hasText:"尚未配置"}).waitFor();
  assert.equal(await calls(),0);
 });
 await check("key settings never echo the secret and do not contact the model",async()=>{
  await page.locator(".pc-settings>summary").click();
  await page.getByLabel("项目规划 API Key",{exact:true}).fill("qa-creation-only");
  await page.getByRole("button",{name:"保存规划 Agent 配置",exact:true}).click();
  await page.getByRole("status").filter({hasText:"配置已保存"}).waitFor();
  assert.equal(await page.getByLabel("项目规划 API Key",{exact:true}).inputValue(),"");
  const settings=await page.evaluate(async()=>await(await fetch('/api/cim/planner/settings')).json());
  assert.ok(settings.has_key);assert.ok(!JSON.stringify(settings).includes("qa-creation-only"));
  assert.equal(await calls(),0);
 });
 await check("planning asks about unknown CPU and follow-up auto-configures existing capabilities",async()=>{
  await page.getByRole("button",{name:"让 Agent 梳理需求",exact:true}).click();
  await page.getByRole("heading",{name:"规划草案 · 待你核对",exact:true}).waitFor();
  assert.equal(await page.getByLabel("规划 CPU",{exact:true}).inputValue(),"");
  assert.match(await page.locator(".pc-questions").first().innerText(),/CPU/);
  assert.ok(await page.getByRole("button",{name:"按配置创建项目与任务",exact:true}).isDisabled());
  await page.getByLabel("规划补充说明",{exact:true}).fill("确认 CPU 为 Q26UDV，范围只有这一台 LUL。其余不确定项保留待确认。");
  await page.getByRole("button",{name:"提交补充并更新草案",exact:true}).click();
  await page.locator(".pc-preview").waitFor();
  assert.equal(await page.getByLabel("规划 CPU",{exact:true}).inputValue(),"Q26UDV");
  assert.equal(await page.locator(".pc-setup-stages article").count(),7);
  assert.ok(await page.locator(".pc-check").filter({hasText:"fa-starter"}).locator('input[type="checkbox"]').isChecked());
  const check=await page.locator(".pc-check").filter({hasText:"fa-starter"}).locator('input[type="checkbox"]').boundingBox();
  const text=await page.locator(".pc-check").filter({hasText:"fa-starter"}).locator("span").boundingBox();
  assert.ok(check.width<=18&&text.width>120,"Pack checkboxes must leave readable label width");
  assert.equal(await calls(),2);
  await page.evaluate(()=>window.scrollTo(0,0));await page.waitForTimeout(350);
  await page.screenshot({path:resolve(qa,"screenshots/project-agent-preview.png"),fullPage:true});
 });
 await check("manual edits invalidate preview; creation saves queued tasks, skills and pack snapshots",async()=>{
  const name="Agent 浏览器创建-"+Date.now();
  await page.getByLabel("规划项目名称",{exact:true}).fill(name);
  assert.ok(await page.getByRole("button",{name:"按配置创建项目与任务",exact:true}).isDisabled());
  await page.getByRole("button",{name:"预览专家、Skill 与任务流程",exact:true}).click();
  await page.locator(".pc-preview").waitFor();
  await page.getByRole("button",{name:"按配置创建项目与任务",exact:true}).click();
  await page.getByRole("heading",{name,exact:true}).waitFor();
  await page.locator('.wf-map[aria-busy="false"]').waitFor();
  const p=await page.getByLabel("选择业务项目",{exact:true}).inputValue();
  const detail=await page.evaluate(async id=>await(await fetch(`/api/cim/projects/${id}`)).json(),p);
  assert.ok(!detail.project.requirements_confirmed && detail.tasks.length>0);
  assert.ok(detail.tasks.every(t=>t.status==="queued"&&t.definition.process_packs[0].id==="fa-starter"));
  assert.equal(detail.attempts.length,0);assert.equal(detail.verification.length,0);
  assert.equal(await calls(),2);
  await page.screenshot({path:resolve(qa,"screenshots/project-agent-created.png"),fullPage:true});
 });
 await check("pack page explains Agent, Skill and pack use; workflow stays usable at 1024",async()=>{
  await page.getByRole("button",{name:"工艺能力包",exact:true}).click();
  await page.getByRole("heading",{name:"工艺能力包：把工艺知识带进项目任务",exact:true}).waitFor();
  await page.getByRole("button",{name:"查看完整工作流",exact:true}).click();
  await page.setViewportSize({width:1024,height:1000});
  await page.getByRole("heading",{name:"从需求到归档，每一步怎么做",exact:true}).waitFor();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
  await page.screenshot({path:resolve(qa,"screenshots/workflow-guide-1024.png"),fullPage:true});
 });
 assert.deepEqual(errors,[]);
 await writeFile(resolve(qa,"planner-browser-results.json"),JSON.stringify({passed:tests,pageErrors:errors,model_mode:"injected synthetic fixture; no paid API call",model_calls:await calls()},null,2));
 console.log(JSON.stringify({passed:tests.length,browser:"Edge headless",pageErrors:errors,paid_api_calls:0}));
}catch(error){
 await page?.screenshot({path:resolve(qa,"screenshots/planner-failure.png"),fullPage:true});
 if(page)await writeFile(resolve(qa,"planner-browser-failure.txt"),await page.locator("body").innerText());
 throw error;
}finally{
 await browser?.close();server.kill();await writeFile(resolve(qa,"planner-browser-server.log"),log);
}
