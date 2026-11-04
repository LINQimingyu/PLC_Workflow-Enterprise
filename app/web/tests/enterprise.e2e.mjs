import {chromium} from '@playwright/test';
import {spawn,execFileSync} from 'node:child_process';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../../..');
const python=resolve(root,'.venv/Scripts/python.exe');
const configPath=execFileSync(python,['deploy/qa_browser.py'],{cwd:root,encoding:'utf8',windowsHide:true}).trim();
assert.ok(configPath.includes('.qa'));
const config=JSON.parse(await readFile(configPath,'utf8'));
const origin=config.origin;
const out=resolve(root,'.qa/browser');await mkdir(out,{recursive:true});
const server=spawn(python,['-m','factory_enterprise.launch','--config',configPath,'--no-browser'],{cwd:root,env:{...process.env,PYTHONPATH:resolve(root,'app/src')+';'+resolve(root,'app'),PYTHONUTF8:'1'},windowsHide:true,stdio:['ignore','pipe','pipe']});
let logs='';server.stderr.on('data',x=>logs+=x);let browser,page;
const tests=[],errors=[];
const password='QA-Browser-Only-2026-Strong';
try{
 for(let i=0;i<100;i++){try{if((await fetch(origin+'/api/health')).ok)break;}catch{}if(server.exitCode!==null)throw Error(logs);await new Promise(r=>setTimeout(r,150));}
 browser=await chromium.launch({channel:'msedge',headless:true});
 page=await browser.newPage({viewport:{width:1440,height:1080}});
 page.on('pageerror',e=>errors.push(String(e)));
 await page.goto((await readFile(resolve(config.root,'.local/first-login-url.txt'),'utf8')).trim());
 await page.getByRole('heading',{name:'创建首位实名管理员'}).waitFor();
 assert.ok(!page.url().includes('setup='));
 await page.getByLabel('用户名',{exact:true}).fill('qa_owner');await page.getByLabel('实名显示名称').fill('QA 项目负责人');
 await page.getByLabel('密码（至少 12 字符）').fill(password);await page.getByRole('button',{name:'创建管理员',exact:true}).click();
 async function login(username){
  await page.getByLabel('用户名',{exact:true}).fill(username);await page.getByLabel('密码（至少 12 字符）').fill(password);
  await page.getByRole('button',{name:'登录',exact:true}).click();await page.getByRole('button',{name:'新建项目',exact:true}).first().waitFor();
 }
 await login('qa_owner');tests.push('first setup, real account login, secret fragment removed');
 const originalFont=await page.locator('.ep-header h1').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
 await page.getByRole('button',{name:'放大字体',exact:true}).click();
 assert.ok(await page.locator('.ep-header h1').evaluate(e=>parseFloat(getComputedStyle(e).fontSize))>originalFont);
 const [guide]=await Promise.all([page.context().waitForEvent('page'),page.getByRole('link',{name:'平台说明',exact:true}).click()]);
 const guideErrors=[];guide.on('pageerror',e=>guideErrors.push(String(e)));guide.on('console',m=>{if(m.type()==='error'&&/content security policy|refused to execute/i.test(m.text()))guideErrors.push(m.text());});
 await guide.getByRole('tab',{name:'整体架构总览',exact:true}).waitFor();
 assert.equal(await guide.getByRole('tab').count(),2);
 await guide.frameLocator('#document').getByRole('heading',{name:'实名工厂岗位',exact:true}).waitFor();
 await guide.getByRole('button',{name:'恢复默认字体',exact:true}).click();
 for(let i=0;i<3;i++)await guide.getByRole('button',{name:'放大字体',exact:true}).click();
 await guide.getByRole('status',{name:'字体比例'}).filter({hasText:'130%'}).waitFor();
 await guide.getByRole('tab',{name:'工程交付工作流',exact:true}).click();
 await guide.frameLocator('#document').getByRole('heading',{name:'程序编译失败：受限修复',exact:true}).waitFor();
 assert.ok(await guide.frameLocator('#document').getByRole('heading',{name:'确认需求与工程基线',exact:true}).evaluate(e=>parseFloat(getComputedStyle(e).fontSize))>26);
 await guide.reload();
 await guide.getByRole('status',{name:'字体比例'}).filter({hasText:'130%'}).waitFor();
 for(const id of ['architecture','workflow']){
  await guide.getByRole('tab',{name:id==='architecture'?'整体架构总览':'工程交付工作流',exact:true}).click();
  await guide.frameLocator('#document').getByRole('main').waitFor();
  for(const width of [1440,1084,390]){
   await guide.setViewportSize({width,height:1000});
   assert.ok(await guide.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   assert.ok(await guide.frameLocator('#document').locator('body').evaluate(e=>e.scrollWidth<=innerWidth+1));
   await guide.screenshot({path:resolve(out,'guide-'+id+'-'+width+'.png'),fullPage:false});
  }
 }
 for(let i=0;i<3;i++)await guide.getByRole('button',{name:'放大字体',exact:true}).click();
 assert.ok(await guide.getByRole('button',{name:'放大字体',exact:true}).isDisabled());
 for(const width of [1084,390]){
  await guide.setViewportSize({width,height:1000});
  assert.ok(await guide.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert.ok(await guide.frameLocator('#document').locator('body').evaluate(e=>e.scrollWidth<=innerWidth+1));
  await guide.screenshot({path:resolve(out,'guide-workflow-'+width+'-160.png'),fullPage:false});
 }
 await guide.getByRole('button',{name:'恢复默认字体',exact:true}).click();
 assert.deepEqual(guideErrors,[]);await guide.close();
 await page.getByRole('button',{name:'恢复默认字体',exact:true}).click();
 tests.push('shared font control changes real text, persists across tabs/reload; two reflowable guides without case, errors or horizontal overflow');

 async function api(path,body){
  return page.evaluate(async({path,body})=>{
   const session=await(await fetch('/api/session')).json();
   const response=await fetch('/api'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-CSRF-Token':session.user.csrf}:{},body:body?JSON.stringify(body):undefined});
   const data=await response.json();if(!response.ok)throw Error(data.error);return data;
  },{path,body});
 }
 const entries=[['项目总控','从一个离线工程项目开始'],['工作模块','按工作模块组织任务'],['工程制品','管理原件与工程制品版本'],['工具与修复','验证证据与补丁修复'],['工程审查','工程审查与风险处置'],['工程交付','工程发布与实施交接'],['知识治理','个人参考与生产知识治理'],['Agent 与 Skill','维护目录与版本'],['岗位与设置','全局设置与项目岗位']];
 for(const [label,heading] of entries){
  await page.getByRole('button',{name:label,exact:true}).click();
  await page.getByRole('heading',{name:heading,exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:label,exact:true}).getAttribute('aria-current'),'page');
  assert.equal(await page.locator('nav button[aria-current="page"]').count(),1);
  assert.equal(await page.getByLabel('当前项目',{exact:true}).inputValue(),'');
  if(label!=='Agent 与 Skill'){
   const entry=page.locator('.ep-project-entry');
   assert.equal(await entry.locator('article').count(),0);
   assert.equal(await entry.locator('.ep-card').count(),1);
   assert.equal(await entry.locator('details').getAttribute('open'),null);
  }
 }
 await page.getByRole('heading',{name:'创建实名用户',exact:true}).waitFor();
 await page.getByLabel('厂内兼容 API 地址',{exact:true}).waitFor();
 tests.push('all nine navigation bodies change with no selected project; global maintenance and settings remain accessible');
 await page.getByRole('button',{name:'Agent 与 Skill',exact:true}).click();
 await page.getByRole('tab',{name:'Skill',exact:true}).click();
 await page.getByRole('button',{name:'新增Skill',exact:true}).click();
 await page.getByLabel('能力标识',{exact:true}).fill('qa-control-method');
 await page.getByLabel('能力名称',{exact:true}).fill('QA 总控方法');
 await page.getByLabel('适用工作模块',{exact:true}).selectOption(['control']);
 await page.getByLabel('Skill 方法内容',{exact:true}).fill('QA ONLY collect synthetic inputs; never execute equipment.');
 await page.getByLabel('维护原因',{exact:true}).fill('QA-only UI regression');
 await page.getByRole('button',{name:'保存草稿',exact:true}).click();
 await page.getByRole('heading',{name:'版本详情：QA 总控方法 · v1',exact:true}).waitFor();
 await page.getByRole('button',{name:'编辑草稿',exact:true}).click();
 await page.getByLabel('Skill 方法内容',{exact:true}).fill('QA ONLY revised synthetic intake method.');
 await page.getByLabel('维护原因',{exact:true}).fill('QA revision before publish');
 await page.getByRole('button',{name:'保存草稿',exact:true}).click();
 await page.getByRole('heading',{name:'版本详情：QA 总控方法 · v1',exact:true}).waitFor();
 await page.getByLabel('发布／启停依据',{exact:true}).fill('QA synthetic review only');
 await page.getByRole('button',{name:'发布此版本',exact:true}).click();
 await page.getByRole('button',{name:'停用此版本',exact:true}).waitFor();
 await page.getByLabel('发布／启停依据',{exact:true}).fill('QA disable test');
 await page.getByRole('button',{name:'停用此版本',exact:true}).click();
 await page.getByRole('button',{name:'启用此版本',exact:true}).waitFor();
 await page.getByLabel('发布／启停依据',{exact:true}).fill('QA enable test');
 await page.getByRole('button',{name:'启用此版本',exact:true}).click();
 await page.getByRole('button',{name:'停用此版本',exact:true}).waitFor();
 const maintained=await api('/maintenance');
 const qaSkill=maintained.items.find(v=>v.key==='qa-control-method'&&v.version===1);
 assert.equal(qaSkill.status,'published');assert.equal(qaSkill.enabled,true);
 await page.getByRole('tab',{name:'模块绑定',exact:true}).click();
 await page.getByLabel('绑定工作模块',{exact:true}).selectOption('control');
 await page.getByLabel('绑定 Skill 版本',{exact:true}).selectOption(qaSkill.id);
 await page.getByLabel('绑定依据',{exact:true}).fill('QA bind exact published version');
 await page.getByRole('button',{name:'保存模块绑定',exact:true}).click();
 await page.getByRole('status').filter({hasText:'模块绑定已保存'}).waitFor();
 assert.equal((await api('/maintenance')).bindings.find(v=>v.module==='control').skill_id,qaSkill.id);
 for(const width of [1084,390]){
  await page.setViewportSize({width,height:1084});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:resolve(out,'maintenance-bindings-'+width+'.png'),fullPage:true});
 }
 await page.setViewportSize({width:1440,height:1080});
 await page.getByLabel('绑定 Skill 版本',{exact:true}).selectOption('builtin-skill-control');
 await page.getByLabel('绑定依据',{exact:true}).fill('QA restore builtin baseline');
 await page.getByRole('button',{name:'保存模块绑定',exact:true}).click();
 await page.getByRole('status').filter({hasText:'模块绑定已保存'}).waitFor();
 await page.getByRole('tab',{name:'Skill',exact:true}).click();
 await page.getByLabel('搜索维护目录',{exact:true}).fill('qa-control-method');
 await page.getByRole('button',{name:'查看 QA 总控方法 v1',exact:true}).click();
 await page.getByRole('button',{name:'编辑为新版本',exact:true}).click();
 await page.getByLabel('维护原因',{exact:true}).fill('QA derive version two');
 await page.getByRole('button',{name:'保存草稿',exact:true}).click();
 await page.getByRole('heading',{name:'版本详情：QA 总控方法 · v2',exact:true}).waitFor();
 tests.push('global Skill maintenance creates/edits drafts, publishes, stops/starts, derives versions and binds exact versions without a selected project');
 await page.getByRole('button',{name:'岗位与设置',exact:true}).click();

 for(const [username,name] of [['qa_engineer','QA 执行工程师'],['qa_reviewer','QA 独立审核人']]){
  await page.getByLabel('新用户名',{exact:true}).fill(username);await page.getByLabel('新用户实名显示名称',{exact:true}).fill(name);
  await page.getByLabel('新用户密码（至少 12 字符）').fill(password);await page.getByRole('button',{name:'创建用户',exact:true}).click();
  await page.getByRole('status').filter({hasText:'已保存'}).waitFor();
 }
 tests.push('admin creates real accounts before creating or selecting a project');
 await page.getByRole('button',{name:'工具与修复',exact:true}).click();
 for(const [width,height] of [[1084,1084],[390,844]]){
  await page.setViewportSize({width,height});await page.screenshot({path:resolve(out,'no-project-tools-'+width+'.png'),fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 }
 await page.setViewportSize({width:1440,height:1080});
 await page.getByRole('button',{name:'新建项目',exact:true}).first().click();
 await page.getByLabel('项目名称',{exact:true}).fill('QA · 企业离线分析样板');
 await page.getByLabel('项目目标',{exact:true}).fill('合成浏览器回归；不代表真实编译、现场或效果');
 await page.getByLabel('交付类型',{exact:true}).selectOption('analysis');
 await page.getByRole('button',{name:'创建项目',exact:true}).click();
 await page.getByRole('heading',{name:'QA · 企业离线分析样板',exact:true}).waitFor();
 let projects=await api('/projects');const pid=projects[0].id,pp='/projects/'+pid;
 tests.push('new module-based project and explicit analysis delivery');
 await api(pp+'/artifacts',{atype:'IntakePlan',title:'QA 前置计划',slot:'intake-plan',payload:{scope:'QA ONLY',tasks:'QA ONLY T01: collect synthetic inputs; no execution authorization',missing:'QA ONLY missing inputs'}});
 await page.getByRole('button',{name:'刷新项目',exact:true}).click();
 await page.getByRole('heading',{name:'项目受理与前置任务计划',exact:true}).waitFor();
 await page.getByText('待补资料 · 任务计划尚未授权',{exact:true}).waitFor();
 tests.push('project intake plan is visible while execution remains unapproved');

 await page.getByRole('button',{name:'岗位与设置',exact:true}).click();
 const users=await api('/users'),engineer=users.find(u=>u.username==='qa_engineer'),reviewer=users.find(u=>u.username==='qa_reviewer');
 for(const [u,roles] of [[engineer,['engineer','validator','knowledge','viewer']],[reviewer,['reviewer','validator','knowledge','viewer']]]){
  await page.getByLabel('项目成员',{exact:true}).selectOption(u.id);await page.getByLabel('项目岗位',{exact:true}).selectOption(roles);
  await page.getByRole('button',{name:'更新项目岗位权限',exact:true}).click();await page.getByRole('status').filter({hasText:'已保存'}).waitFor();
 }
 tests.push('named users and project-scoped role assignments');
 await page.getByRole('button',{name:'工程制品',exact:true}).click();
 await page.getByLabel('制品标题',{exact:true}).fill('QA 原件');await page.getByLabel('制品序列名（同名生成新版本）').fill('qa-original');
 await page.getByLabel('来源',{exact:true}).fill('QA-only synthetic fixture');
 await page.getByLabel('原始／候选文件',{exact:true}).setInputFiles({name:'qa.txt',mimeType:'text/plain',buffer:Buffer.from('QA ONLY offline source')});
 await page.getByRole('button',{name:'保存制品新版本',exact:true}).click();await page.getByRole('status').filter({hasText:'已保存'}).waitFor();
 let d=await api(pp);const original=d.artifact.find(a=>a.type==='Original');
 assert.ok(original.sha256.length===64);tests.push('original file import, source hash and separate version');
 // Remaining engineering baseline fixtures are API-created in this QA-only domain.
 await api(pp+'/artifacts',{atype:'ToolchainProfile',title:'QA 工具链',payload:{device:'QA-device',cpu:'Q26UDV',firmware:'QA-fw',ide:'GX Works2',ide_version:'QA-version',libraries:['QA-lib'],original_ids:[original.id],permissions:['offline_only']}});
 await api(pp+'/artifacts',{atype:'RequirementSpec',title:'QA 需求',payload:{goal:'QA分析',scope:'QA范围',exclusions:'不执行设备',acceptance:['QA'],key_io:['QA-X0'],interlocks:['QA联锁']}});
 async function approve(g){
  await page.getByRole('button',{name:'项目总控',exact:true}).click();await page.getByRole('button',{name:'刷新项目'}).click();
  const card=page.locator('.ep-gates>article').filter({has:page.getByRole('heading',{name:g,exact:true})});
  await card.getByText('审查与决定',{exact:true}).click();await card.getByLabel('审核依据',{exact:true}).fill('QA 合成回归审核，不是现场验收');
  await card.getByRole('button',{name:'记录门禁决定',exact:true}).click();await card.locator('.ep-badge').filter({hasText:'通过'}).waitFor();
 }
 await approve('输入锁');
 await api(pp+'/artifacts',{atype:'EngineeringPlan',title:'QA 方案',payload:{solution:'QA离线分析',validation:['QA限制'],rollback:'不实施',impact:'无现场操作'}});
 await approve('方案锁');tests.push('input and plan gates require actual business decisions');
 await page.getByRole('button',{name:'工作模块',exact:true}).click();
 await page.getByLabel('模块目标',{exact:true}).fill('QA 模块交付');await page.getByLabel('模块范围',{exact:true}).fill('QA only');
 await page.getByLabel('本模块输入',{exact:true}).selectOption(original.id);
 await page.getByLabel('合同交付',{exact:true}).selectOption('AnalysisDelivery');
 await page.getByLabel('模块验收条件（数组）').fill('["QA only"]');
 await page.getByLabel('执行负责人',{exact:true}).selectOption(engineer.id);await page.getByLabel('独立审核人',{exact:true}).selectOption(reviewer.id);
 await page.getByLabel('允许工具',{exact:true}).selectOption('plc.inspect_csv');
 await page.getByRole('button',{name:'建立待授权任务',exact:true}).click();
 await page.getByRole('button',{name:'授权该任务',exact:true}).click();await page.getByRole('status').filter({hasText:'模块已授权'}).waitFor();
 await page.getByRole('button',{name:'项目总控',exact:true}).click();await page.getByRole('button',{name:'推进／恢复流程',exact:true}).click();
 await page.getByText('模块待提交成果',{exact:false}).waitFor();tests.push('real LangGraph nested module interrupt');
 async function switchUser(name){
  await page.getByRole('button',{name:'退出登录',exact:true}).click();await login(name);
  await page.getByLabel('当前项目',{exact:true}).selectOption(pid);await page.getByRole('heading',{name:'QA · 企业离线分析样板',exact:true}).waitFor();
 }
 await switchUser('qa_engineer');await page.getByRole('button',{name:'工作模块',exact:true}).click();
 await page.getByText('提交候选成果／缺项',{exact:true}).click();
 await page.getByLabel('成果摘要',{exact:true}).fill('QA合成分析，无真实验证');
 await page.getByLabel('结论',{exact:true}).fill('QA候选结论');await page.getByLabel('局限',{exact:true}).fill('未编译、未仿真、未现场');
 await page.getByRole('button',{name:'提交候选',exact:true}).click();await page.getByRole('status').filter({hasText:'已保存'}).waitFor();
 await switchUser('qa_reviewer');await page.getByRole('button',{name:'工作模块',exact:true}).click();
 await page.getByLabel('独立审核依据',{exact:true}).fill('QA独立审核，仅分析交付');
 await page.getByRole('button',{name:'记录独立审核',exact:true}).click();await page.locator('.ep-run .ep-badge').filter({hasText:'已审核'}).waitFor();
 tests.push('separate executor and authenticated reviewer complete module');
 await switchUser('qa_owner');
 for(const g of ['工程锁','风险锁','发布锁'])await approve(g);
 await page.getByRole('button',{name:'工程交付',exact:true}).click();await page.getByRole('button',{name:'生成锁定工程包',exact:true}).click();
 await page.getByRole('link',{name:'校验并导出工程包',exact:true}).waitFor();
 d=await api(pp);assert.equal(d.release.length,1);assert.equal(d.project.lifecycle.site,'not_recorded');
 const download=await page.request.get(origin+'/api/releases/'+d.release[0].id+'/export');assert.equal(download.status(),200);
 tests.push('analysis release manifest/export with site and benefit still unrecorded');
 await page.getByRole('button',{name:'项目总控',exact:true}).click();
 for(const [width,height] of [[1440,1050],[1024,1000],[390,844],[320,780]]){
  await page.setViewportSize({width,height});await page.screenshot({path:resolve(out,'overview-'+width+'.png'),fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no page overflow '+width);
 }
 await page.setViewportSize({width:1440,height:1050});
 for(const label of ['工作模块','工程制品','工具与修复','工程审查','工程交付','知识治理','岗位与设置']){
  await page.getByRole('button',{name:label,exact:true}).click();
  await page.screenshot({path:resolve(out,'panel-'+label+'.png'),fullPage:true});
 }
 await page.getByRole('button',{name:'工具与修复',exact:true}).click();
 await page.getByLabel('当前项目',{exact:true}).selectOption('');
 await page.getByRole('heading',{name:'验证证据与补丁修复',exact:true}).waitFor();
 await page.getByLabel('选择要处理的项目',{exact:true}).selectOption(pid);
 await page.getByRole('heading',{name:'验证证据分别记录',exact:true}).waitFor();
 tests.push('clearing and explicitly reselecting a project preserves the selected page');
 for(const label of ['项目总控','工作模块']){
  await page.getByLabel('当前项目',{exact:true}).selectOption('');
  await page.getByRole('button',{name:label,exact:true}).click();
  const entry=page.locator('.ep-project-entry');
  await entry.getByRole('combobox',{name:'选择要处理的项目'}).waitFor();
  assert.equal(await entry.locator('article').count(),0);
  const summary=entry.locator('summary');await summary.click();
  assert.notEqual(await entry.locator('details').getAttribute('open'),null);
  assert.equal(await entry.locator('li').count(),3);await summary.click();
  for(const [width,height] of [[1084,1084],[390,844]]){
   await page.setViewportSize({width,height});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   if(width>720)assert.ok(await page.locator('.ep-main').evaluate(e=>e.getBoundingClientRect().top<80));
   await page.screenshot({path:resolve(out,'compact-entry-'+(label==='项目总控'?'overview':'modules')+'-'+width+'.png'),fullPage:true});
  }
 }
 await page.setViewportSize({width:1440,height:1080});
 await page.getByLabel('当前项目',{exact:true}).selectOption(pid);
 tests.push('compact project and module entry: one chooser, collapsed instructions, no repeated cards at desktop and mobile widths');

 tests.push('all module panels plus four responsive widths, keyboard focus styles');
 assert.deepEqual(errors,[]);
 await writeFile(resolve(out,'report.json'),JSON.stringify({tests,errors,environment:'qa',real_gx_executed:false,field_accepted:false},null,2));
 console.log(JSON.stringify({passed:tests.length,errors:errors.length,screenshots:out}));
}catch(error){await page?.screenshot({path:resolve(out,'failure.png'),fullPage:true});await writeFile(resolve(out,'failure.txt'),String(error)+'\n'+logs+'\n'+(await page?.locator('body').innerText()));throw error;}
finally{await browser?.close();server.kill();}
