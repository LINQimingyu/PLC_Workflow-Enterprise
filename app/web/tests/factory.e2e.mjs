import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const app = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const workspace = resolve(app, ".qa/browser-workspace");
const python = resolve(app, "../.venv/Scripts/python.exe");
const origin = "http://127.0.0.1:18772";
const runStarted = Date.now();
await mkdir(resolve(app, ".qa/screenshots"), { recursive: true });
const server = spawn(python, ["-m", "cim.launch", "--port", "18772", "--workspace", workspace], { cwd: app, env: { ...process.env, PYTHONPATH: resolve(app, "src"), PYTHONUTF8: "1" }, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
let serverLog = "";
server.stderr.on("data", d => { serverLog += d; });
const browserErrors = [], tests = [];
let browser, page;
async function check(name, fn) { await fn(); tests.push(name); }
try {
  for (let n = 0; n < 100; n++) {
    try { if ((await fetch(`${origin}/api/health`)).ok && (await stat(resolve(workspace, ".local/login-url.txt"))).mtimeMs >= runStarted) break; } catch {}
    if (server.exitCode !== null) throw new Error(serverLog);
    if (n === 99) throw new Error("Server startup timed out");
    await new Promise(r => setTimeout(r, 150));
  }
  browser = await chromium.launch({ channel: "msedge", headless: true });
  page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  page.on("pageerror", e => browserErrors.push(String(e)));
  await page.goto((await readFile(resolve(workspace, ".local/login-url.txt"), "utf8")).trim());
  await page.getByRole("button", { name: "＋ 新建项目" }).waitFor();
  await check("font controls resize text, persist, reset and reflow on narrow screens", async () => {
    const reset = () => page.getByRole("button", { name: "恢复默认字号", exact: true }).click();
    await reset();
    const base = await page.locator(".fc-top h1").evaluate(el => parseFloat(getComputedStyle(el).fontSize));
    await page.getByRole("button", { name: "放大字号", exact: true }).click();
    assert.equal(await page.getByLabel("当前字号", { exact: true }).innerText(), "110%");
    const larger = await page.locator(".fc-top h1").evaluate(el => parseFloat(getComputedStyle(el).fontSize));
    assert.ok(Math.abs(larger / base - 1.1) < 0.01, "Text really scales");
    await page.getByRole("button", { name: "放大字号", exact: true }).click();
    await page.getByRole("button", { name: "放大字号", exact: true }).click();
    assert.ok(await page.getByRole("button", { name: "放大字号", exact: true }).isDisabled());
    await page.reload();
    await page.getByLabel("当前字号", { exact: true }).filter({ hasText: "130%" }).waitFor();
    await page.setViewportSize({ width: 320, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
    await page.screenshot({ path: resolve(app, ".qa/screenshots/font-size-130-mobile.png"), fullPage: true });
    await reset();
    await page.getByRole("button", { name: "缩小字号", exact: true }).click();
    assert.ok(await page.getByRole("button", { name: "缩小字号", exact: true }).isDisabled());
    await reset();
    await page.setViewportSize({ width: 1440, height: 1050 });
  });
  const name = `浏览器验收-${Date.now()}`;
  await check("create and retain the selected business project", async () => {
    await page.getByRole("button", { name: "＋ 新建项目" }).click();
    await page.getByLabel("项目名称", { exact: true }).fill(name);
    await page.getByLabel("设备类型 / 机台").fill("LUL Conveyor");
    await page.getByLabel("现状、目标、范围与验收要求").fill("浏览器离线验收：一台 LUL 的马达负载上报；检查点表与断线行为。");
    await page.getByRole("button", { name: "建立项目", exact: true }).click();
    await page.getByRole("heading", { name, exact: true }).waitFor();
  });
  await check("upload a source and retrieve its exact citation", async () => {
    await page.getByRole("button", { name: "资料与检索", exact: true }).click();
    await page.getByLabel("资料分级", { exact: true }).selectOption("internal");
    await page.locator('input[type="file"]').first().setInputFiles({ name: "browser-source.md", mimeType: "text/markdown", buffer: Buffer.from("马达负载上报：需确认工程点表，断线数据标注无效。") });
    await page.getByRole("cell", { name: /browser-source.md/ }).waitFor();
    await page.getByLabel("检索词", { exact: true }).fill("马达负载");
    await page.getByRole("button", { name: "检索证据", exact: true }).click();
    await page.locator(".fc-hit").first().waitFor();
    assert.match(await page.locator(".fc-hit").first().innerText(), /line:1/);
  });
  await check("confirm inputs, plan experts and download a bound task bundle", async () => {
    await page.getByRole("button", { name: "项目概览", exact: true }).click();
    await page.getByLabel("确认人", { exact: true }).fill("浏览器测试执行人");
    await page.getByRole("button", { name: "确认当前需求", exact: true }).click();
    await page.getByRole("button", { name: "生成本项目专家任务", exact: true }).click();
    await page.getByRole("button", { name: "专家任务", exact: true }).click();
    await page.locator('.wf-map[aria-busy="false"]').waitFor();
    assert.equal(await page.locator(".wf-canvas").count(), 0, "Map starts collapsed");
    assert.equal(await page.locator(".wf-stage-strip li").count(), 7);
    await page.locator(".fc-task-waiting>summary").click();
    const blocked = page.getByRole("region", { name: "等待前置或状态更新", exact: true });
    await blocked.getByRole("button", { name: "创建执行批次", exact: true }).first().waitFor();
    assert.ok(await blocked.getByRole("button", { name: "创建执行批次", exact: true }).count() > 0);
    assert.ok(await blocked.getByRole("button", { name: "创建执行批次", exact: true }).first().isDisabled());
    await page.locator(".fc-task-waiting>summary").click();
    await page.getByRole("button", { name: "创建执行批次", exact: true }).first().click();
    await page.getByRole("link", { name: "下载任务包", exact: true }).first().waitFor();
    const download = page.waitForEvent("download");
    await page.getByRole("link", { name: "下载任务包", exact: true }).first().click();
    assert.match((await download).suggestedFilename(), /\.zip$/);
    const template = JSON.parse(await page.getByLabel("任务回传 JSON", { exact: true }).inputValue());
    template.summary = "仅为离线浏览器验收，已记录缺项；没有实际编译或现场操作。";
    template.verdict = "candidate";
    await page.locator(".fc-return-editor>summary").click();
    await page.getByLabel("任务回传 JSON", { exact: true }).fill("{invalid");
    await page.getByRole("alert").filter({ hasText: "不是有效的 JSON 对象" }).waitFor();
    assert.ok(await page.getByRole("button", { name: "提交回传", exact: true }).isDisabled());
    await page.getByLabel("任务回传 JSON", { exact: true }).fill(JSON.stringify({ ...template, input_revision: 999 }));
    await page.getByRole("alert").filter({ hasText: "不匹配" }).waitFor();
    assert.ok(await page.getByRole("button", { name: "提交回传", exact: true }).isDisabled());
    await page.getByLabel("任务回传 JSON", { exact: true }).fill(JSON.stringify(template));
    await page.getByLabel("回传摘要", { exact: true }).getByText(template.summary, { exact: true }).waitFor();
    await page.getByRole("button", { name: "提交回传", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "回传已保存；尚未人工审查" }).waitFor();
    await page.getByLabel("审查人", { exact: true }).fill("浏览器审查夹具");
    await page.getByLabel("审查意见", { exact: true }).fill("仅验收任务流转，非现场技术接受。");
    await page.getByRole("button", { name: "审查通过", exact: true }).click();
    await page.locator(".fc-task-detail .fc-badge.approved").waitFor();
    assert.ok(await page.getByRole("button", { name: "提交回传", exact: true }).isDisabled());
    await page.locator(".fc-task-list .fc-task-select").first().click();
    const ended = page.locator(".fc-task-list details").filter({ hasText: "已审查 / 已取消" });
    await ended.locator(":scope > summary").click();
    await ended.locator(".fc-task-select").click();
    await page.getByLabel("回传摘要", { exact: true }).getByText(template.summary, { exact: true }).waitFor();
    await ended.locator(":scope > summary").click();
    await page.locator(".fc-return-editor>summary").click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(app, ".qa/screenshots/ui-task-workspace.png"), fullPage: true });
    for (const width of [1024, 390, 320]) {
      await page.setViewportSize({ width, height: 1050 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
    }
    await page.screenshot({ path: resolve(app, ".qa/screenshots/ui-task-mobile.png"), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1050 });
  });
  await check("browse actual agent and skill catalogs and preserve native workbench", async () => {
    await page.getByRole("button", { name: /专家目录/ }).click();
    assert.equal(await page.locator(".fc-card").count(), 34);
    await page.screenshot({ path: resolve(app, ".qa/screenshots/agents.png"), fullPage: false });
    await page.getByRole("button", { name: /Skill 方法库/ }).click();
    assert.equal(await page.locator(".fc-card").count(), 41);
    await page.getByRole("link", { name: /GXWorks 原生工程工作台/ }).click();
    await page.getByRole("link", { name: /面板工厂工作台/ }).waitFor();
    await page.getByRole("link", { name: /面板工厂工作台/ }).click();
    await page.getByRole("heading", { name, exact: true }).waitFor();
  });
  await check("estimate and archive with business forms while unknowns remain unknown", async () => {
    await page.getByRole("button", { name: "方案与投入", exact: true }).click();
    await page.getByLabel("物料1规格", { exact: true }).fill("SENSOR-QA");
    await page.getByLabel("物料1数量", { exact: true }).fill("2");
    await page.getByLabel("程序修改人天", { exact: true }).fill("1");
    await page.getByLabel("离线测试人天", { exact: true }).fill("2");
    await page.getByLabel("人天费率", { exact: true }).fill("1000");
    await page.getByLabel("收益计算依据", { exact: true }).fill("仅供浏览器表单测试，未知报价和现场收益不估造。");
    await page.getByRole("button", { name: "核算并保存方案", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "投入收益测算已保存" }).waitFor();
    await page.getByText("BOM 价格未知: SENSOR-QA", { exact: true }).waitFor();
    await page.screenshot({ path: resolve(app, ".qa/screenshots/business.png"), fullPage: true });
    await page.getByRole("button", { name: "验证与归档", exact: true }).click();
    assert.equal(await page.locator(".fc-evidence-row").count(), 5);
    await page.getByRole("button", { name: "查看 / 登记现场验证", exact: true }).click();
    assert.equal(await page.getByLabel("验证阶段", { exact: true }).inputValue(), "field");
    await page.getByLabel("项目结局", { exact: true }).selectOption("not_implemented");
    await page.getByLabel("归档责任人", { exact: true }).fill("浏览器测试执行人");
    await page.getByLabel("归档原因", { exact: true }).fill("离线表单验收，未实施真实工程改造。");
    await page.getByLabel("实际投入", { exact: true }).fill("仅测试时间，非现场施工成本。");
    await page.getByRole("button", { name: "检查并归档", exact: true }).click();
    await page.getByRole("link", { name: "下载完整归档包", exact: true }).waitFor();
  });
  await page.getByRole("button", { name: "项目概览", exact: true }).click();
  await page.screenshot({ path: resolve(app, ".qa/screenshots/workbench.png"), fullPage: true });
  await check("responsive layout has no page-wide overflow", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: resolve(app, ".qa/screenshots/mobile.png"), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
  });
  assert.deepEqual(browserErrors, []);
  await writeFile(resolve(app, ".qa/browser-results.json"), JSON.stringify({ passed: tests, pageErrors: browserErrors }, null, 2));
  console.log(JSON.stringify({ passed: tests.length, browser: "Edge headless", pageErrors: browserErrors }));
} catch (error) {
  await page?.screenshot({ path: resolve(app, ".qa/screenshots/failure.png"), fullPage: true });
  if (page) await writeFile(resolve(app, ".qa/browser-failure.txt"), await page.locator("body").innerText());
  throw error;
} finally {
  await browser?.close();
  server.kill();
  await writeFile(resolve(app, ".qa/browser-server.log"), serverLog);
}
