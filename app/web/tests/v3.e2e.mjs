import {chromium} from '@playwright/test';
import {spawn} from 'node:child_process';
import {readFile,mkdir,writeFile,stat} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const app=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const workspace=resolve(app,'.qa/v3-browser-'+Date.now());
const origin='http://127.0.0.1:18775';
await mkdir(resolve(app,'.qa/screenshots'),{recursive:true});
const server=spawn(resolve(app,'../.venv/Scripts/python.exe'),['-m','factory_v3.launch','--port','18775','--workspace',workspace],{cwd:app,env:{...process.env,PYTHONPATH:resolve(app,'src'),PYTHONUTF8:'1'},stdio:['ignore','pipe','pipe'],windowsHide:true});
let logs='';server.stderr.on('data',d=>logs+=d);
let browser;const tests=[],errors=[];
try{
 for(let i=0;i<150;i++){
   try{if((await fetch(origin+'/api/health')).ok&&(await stat(resolve(workspace,'.local/login-url.txt'))).isFile())break;}catch{}
   if(server.exitCode!==null)throw Error(logs);
   if(i===149)throw Error('startup timeout: '+logs);
   await new Promise(r=>setTimeout(r,150));
 }
 browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}});
 page.on('pageerror',e=>errors.push(String(e)));
 await page.goto((await readFile(resolve(workspace,'.local/login-url.txt'),'utf8')).trim());
 await page.getByRole('button',{name:'＋ 新建设备项目',exact:true}).waitFor();
 assert.ok(!page.url().includes('token='));tests.push('session bootstrap removes private login token');
 const before=await page.locator('.v3-top h1').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
 await page.getByRole('button',{name:'放大字号',exact:true}).click();
 const after=await page.locator('.v3-top h1').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
 assert.ok(after>before);await page.getByRole('button',{name:'恢复默认字号',exact:true}).click();tests.push('font controls change rendered font size');
 await page.getByLabel('操作记录姓名',{exact:true}).fill('合成浏览器验收员');
 await page.getByRole('button',{name:'＋ 新建设备项目',exact:true}).click();
 await page.getByLabel('项目名称',{exact:true}).fill('合成 · v3 设备诊断');
 await page.getByLabel('CPU（以设备为准）',{exact:true}).fill('Q26UDV');
 await page.getByLabel('设备名称／类型',{exact:true}).fill('LUL Conveyor');
 await page.getByLabel('资料分级',{exact:true}).selectOption('public');
 await page.getByLabel('现状、目标、纳入／排除范围、验收要求',{exact:true}).fill('合成验收：仅诊断上报逻辑；不改程序、不编译、不现场实施。');
 await page.getByRole('button',{name:'预览模块路线',exact:true}).click();
 await page.getByRole('button',{name:'创建项目与模块',exact:true}).click();
 await page.getByRole('heading',{name:'合成 · v3 设备诊断',exact:true}).waitFor();tests.push('four-scenario project builder creates minimal modules');
 await page.getByRole('button',{name:/01 ·.*范围与验收/}).click();
 await page.getByRole('button',{name:'授权并处理本模块',exact:true}).click();
 await page.getByRole('button',{name:'提交候选交付',exact:true}).waitFor();
 const result={summary:'合成诊断范围已整理；未执行工程与现场操作。',verdict:'candidate',citations:[],findings:[],questions:[],artifacts:[]};
 await page.getByLabel('模块回传 JSON',{exact:true}).fill(JSON.stringify(result));
 await page.getByRole('button',{name:'提交候选交付',exact:true}).click();
 await page.getByLabel('审核／返修依据',{exact:true}).fill('合成测试确认范围和排除项，不代表真实设备接受。');
 await page.getByRole('button',{name:'人工审核接受',exact:true}).click();
 await page.getByRole('status').filter({hasText:'人工接受完成'}).waitFor();tests.push('module authorization return and explicit human gate');
 await page.getByRole('button',{name:'资料与工程',exact:true}).click();
 await page.getByLabel('资料分级',{exact:true}).selectOption('public');
 await page.locator('input[type=file]').setInputFiles({name:'synthetic.txt',mimeType:'text/plain',buffer:Buffer.from('合成点表 D100，单位 %；仅浏览器验收。')});
 await page.getByText('synthetic.txt',{exact:true}).waitFor();tests.push('source upload and provenance visible');
 await page.getByRole('button',{name:'设置与能力',exact:true}).click();
 await page.getByRole('heading',{name:'CIM',exact:true}).waitFor();
 assert.equal(await page.getByRole('heading',{name:'CIM/FDC',exact:true}).count(),0);tests.push('eight module capabilities and CIM terminology');
 await page.getByRole('button',{name:'我的项目',exact:true}).click();
 await page.getByRole('button',{name:'总控台',exact:true}).click();
 await page.screenshot({path:resolve(app,'.qa/screenshots/v3-control.png'),fullPage:true});
 for(const width of [1024,390,320]){
   await page.setViewportSize({width,height:1000});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),`no horizontal overflow at ${width}`);
 }
 await page.screenshot({path:resolve(app,'.qa/screenshots/v3-mobile.png'),fullPage:true});tests.push('responsive 1440 1024 390 320');
 await page.setViewportSize({width:1440,height:1050});
 const security=await page.evaluate(async()=>({csrf:(await fetch('/api/v3/backup',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status}));
 assert.equal(security.csrf,403);tests.push('CSRF write bypass rejected');
 assert.deepEqual(errors,[]);
 await writeFile(resolve(app,'.qa/v3-browser-results.json'),JSON.stringify({tests,errors,passed:true},null,2));
 console.log(JSON.stringify({passed:tests.length,errors:errors.length}));
}finally{await browser?.close();server.kill();}
