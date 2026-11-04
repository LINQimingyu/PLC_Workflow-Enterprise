/** Real browser acceptance, isolated under .qa; all data is synthetic. */
import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const app = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const workspace = resolve(app, ".qa/workflow-browser-workspace");
const origin = "http://127.0.0.1:18773";
const started = Date.now(), tests = [], errors = [];
await mkdir(resolve(app, ".qa/screenshots"), { recursive: true });
const server = spawn(resolve(app, "../.venv/Scripts/python.exe"), ["-m", "cim.launch", "--port", "18773", "--workspace", workspace], {
  cwd: app, env: { ...process.env, PYTHONPATH: resolve(app, "src"), PYTHONUTF8: "1" },
  windowsHide: true, stdio: ["ignore", "ignore", "pipe"],
});
let log = "", browser, page;
server.stderr.on("data", d => { log += d; });
async function check(name, fn) { await fn(); tests.push(name); }
async function request(path, body) {
  return page.evaluate(async ({ path, body }) => {
    const session = await (await fetch("/api/session")).json();
    const response = await fetch(path, { method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "x-csrf-token": session.csrf },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const value = await response.json();
    if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(value)}`);
    return value;
  }, { path, body });
}
async function ready() { await page.locator('.wf-map[aria-busy="false"]').waitFor(); }
try {
  for (let n = 0; n < 100; n++) {
    try { if ((await fetch(origin + "/api/health")).ok && (await stat(resolve(workspace, ".local/login-url.txt"))).mtimeMs >= started) break; } catch {}
    if (server.exitCode !== null) throw new Error(log);
    if (n === 99) throw new Error("Workflow server startup timed out");
    await new Promise(r => setTimeout(r, 150));
  }
  browser = await chromium.launch({ channel: "msedge", headless: true });
  page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  page.on("pageerror", e => errors.push(String(e)));
  await page.goto((await readFile(resolve(workspace, ".local/login-url.txt"), "utf8")).trim());
  await page.getByRole("button", { name: "＋ 新建项目" }).waitFor();
  const name = `流程导航验收-${started}`;
  const p = await request("/api/cim/projects", { name, classification: "internal", equipment: "LUL", requirements: "仅业务与浏览器夹具，不代表实际编译、模拟或现场验收。" });
  const command = (action, data) => request(`/api/cim/projects/${p.id}/commands/${action}`, data);
  const source = await command("document", { expected_revision: 1, name: "navigation-source.md", data_base64: Buffer.from("仅供导航验收的来源资料").toString("base64"), classification: "internal", kind: "source" });
  await command("confirm", { expected_revision: 2, actor: "夹具需求人" });
  const tasks = await command("plan", { expected_revision: 2 });
  const requirements = tasks.filter(t => t.stage === "requirements");
  const attempts = [];
  for (const task of requirements) attempts.push(await command("start", { task_id: task.id, request_id: "browser-" + task.id }));
  await command("verify", { expected_revision: 2, phase: "compile", status: "failed", actor: "隔离夹具", record: "仅测试失败状态的显示，无真实编译", source_ids: [] });
  for (let n = 0; n < 17; n++) { await command("status", { status: "paused" }); await command("status", { status: "active" }); }
  const second = await request("/api/cim/projects", { name: name + "-新项目", classification: "internal", equipment: "LUL", requirements: "第二个隔离项目" });
  await page.evaluate(id => localStorage.setItem("factory-selected-project", id), p.id);
  await page.reload(); await ready();
  await page.getByRole("heading", { name, exact: true }).waitFor();
  const snap = await request(`/api/cim/projects/${p.id}/workflow`);
  const task = requirements[0];
  await check("seven readable stages and all current parallel waiting tasks", async () => {
    assert.equal(await page.locator(".wf-canvas").count(), 0);
    assert.equal(await page.locator(".wf-stage-strip li").count(), 7);
    await page.getByRole("button", { name: "展开地图", exact: true }).click();
    assert.equal(await page.locator(".wf-stage").count(), 7);
    assert.equal(await page.locator(".wf-todos button").count(), 2);
    assert.match(await page.locator(".wf-summary").innerText(), /载入任务回传/);
    const scale = await page.locator(".react-flow__viewport").evaluate(el => new DOMMatrixReadOnly(getComputedStyle(el).transform).a);
    assert.ok(scale >= 0.7, "Default canvas keeps text readable");
    assert.ok(snap.nodes.find(n => n.id === "task:" + task.id).ready);
    const nodeWidth = await page.locator(".wf-stage").first().evaluate(el => parseFloat(getComputedStyle(el).width));
    await page.getByRole("button", { name: "放大字号", exact: true }).click();
    const largerNode = await page.locator(".wf-stage").first().evaluate(el => parseFloat(getComputedStyle(el).width));
    assert.ok(Math.abs(largerNode / nodeWidth - 1.1) < 0.01, "Diagram nodes adapt to larger text");
    await page.getByRole("button", { name: "恢复默认字号", exact: true }).click();
  });
  await check("expand, keyboard selection, task dependencies and exact form navigation", async () => {
    await page.getByRole("button", { name: "展开需求澄清", exact: true }).click();
    assert.equal(await page.locator(".wf-child").count(), 3);
    await page.locator('.react-flow__node[data-id="stage:baseline"]').focus();
    await page.keyboard.press("Enter");
    assert.equal(await page.locator(".wf-guide h3").innerText(), "资料基线");
    await page.locator(".wf-todos button").filter({ hasText: task.definition.agent.name }).click();
    assert.equal(await page.locator(".wf-guide h3").innerText(), task.definition.agent.name);
    assert.ok(await page.locator(".wf-guide").getByRole("button", { name: "资料与工程基线", exact: true }).count() > 0);
    await page.locator(".wf-go").click();
    await page.locator(`section[data-task-id="${task.id}"]`).waitFor();
    const form = JSON.parse(await page.getByLabel("任务回传 JSON", { exact: true }).inputValue());
    assert.equal(form.task_id, task.id);
    assert.equal((await request(`/api/cim/projects/${p.id}`)).attempts.length, attempts.length);
    await page.screenshot({ path: resolve(app, ".qa/screenshots/workflow-1440.png"), fullPage: true });
  });
  await check("zoom, fit, locate-current, minimap, pan, full-screen and escape", async () => {
    await page.getByRole("button", { name: "全屏查看", exact: true }).click();
    await page.locator(".wf-fullscreen").waitFor();
    await page.locator(".wf-legend").getByRole("button", { name: "适应全图", exact: true }).click();
    const viewport = page.locator(".react-flow__viewport");
    const previous = await viewport.getAttribute("style");
    await page.getByRole("button", { name: "放大流程", exact: true }).click();
    await page.waitForFunction(old => document.querySelector(".react-flow__viewport").getAttribute("style") !== old, previous);
    const canvas = await page.locator(".wf-canvas").boundingBox();
    const panBefore = await viewport.getAttribute("style");
    await page.mouse.move(canvas.x + 25, canvas.y + 30); await page.mouse.down();
    await page.mouse.move(canvas.x + 140, canvas.y + 90, { steps: 10 }); await page.mouse.up();
    assert.notEqual(await viewport.getAttribute("style"), panBefore);
    await page.getByRole("button", { name: "定位当前节点", exact: true }).click();
    assert.equal(await page.locator(".wf-guide h3").innerText(), "需求澄清");
    await page.locator(".react-flow__minimap").waitFor();
    await page.screenshot({ path: resolve(app, ".qa/screenshots/workflow-fullscreen.png"), fullPage: false });
    await page.keyboard.press("Escape");
    assert.equal(await page.locator(".wf-fullscreen").count(), 0);
  });
  await check("history loads older records and links to original source", async () => {
    await page.locator(".wf-history>summary").click();
    assert.equal(await page.locator(".wf-history li").count(), 20);
    await page.getByRole("button", { name: "加载更早记录", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll(".wf-history li").length > 20);
    while (await page.getByRole("button", { name: "加载更早记录", exact: true }).count()) {
      const response = page.waitForResponse(r => r.url().includes("before_seq="));
      await page.getByRole("button", { name: "加载更早记录", exact: true }).click(); await response;
      await page.getByRole("button", { name: "加载中…", exact: true }).waitFor({ state: "detached" });
    }
    const seq = await page.locator(".wf-history li").count(); assert.ok(seq > 40);
    await page.locator(".wf-history li").filter({ hasText: "导入来源资料" }).getByRole("button", { name: /查看资料/ }).click();
    await page.locator(`tr[data-document-id="${source.id}"]`).waitFor();
    assert.equal(await page.locator(".fc-tabs .selected").innerText(), "资料与检索");
  });
  await check("verification subnodes link to the correct phase", async () => {
    await page.locator(".wf-legend").getByRole("button", { name: "适应全图", exact: true }).click();
    await page.getByRole("button", { name: "展开工程与现场验证", exact: true }).click();
    await page.locator('.react-flow__node[data-id="verification:compile"]').focus(); await page.keyboard.press("Enter");
    assert.equal(await page.locator(".wf-guide h3").innerText(), "编译");
    assert.match(await page.locator(".wf-guide .wf-state").innerText(), /失败/);
    await page.locator(".wf-go").click();
    await page.getByRole("heading", { name: "工程、现场与效益分别验收", exact: true }).waitFor();
    assert.equal(await page.getByLabel("验证阶段", { exact: true }).inputValue(), "compile");
  });
  await check("collapse, project isolation and reload restore selection", async () => {
    await page.getByRole("button", { name: "收起地图", exact: true }).click();
    assert.equal(await page.locator(".wf-canvas").count(), 0);
    await page.reload(); await ready();
    assert.equal(await page.locator(".wf-canvas").count(), 0);
    await page.getByRole("button", { name: "展开地图", exact: true }).click();
    await page.getByLabel("选择业务项目", { exact: true }).selectOption(second.id); await ready();
    await page.getByRole("heading", { name: second.name, exact: true }).waitFor();
    assert.match(await page.locator(".wf-summary").innerText(), /补齐并确认当前需求/);
    assert.equal(await page.locator(".wf-child").count(), 0);
    await page.getByLabel("选择业务项目", { exact: true }).selectOption(p.id); await ready();
    await page.getByRole("heading", { name, exact: true }).waitFor();
    assert.equal(await page.locator(".wf-guide h3").innerText(), "编译");
  });
  await check("focus refresh reflects externally paused project without editing it", async () => {
    await command("status", { status: "paused" });
    const read = page.waitForResponse(r => r.url().endsWith("/workflow") && r.status() === 200);
    await page.evaluate(() => window.dispatchEvent(new Event("focus"))); await read; await ready();
    assert.match(await page.locator(".wf-summary").innerText(), /查看项目状态并恢复/);
    await command("status", { status: "active" });
  });
  await check("failed reads retain labelled snapshot and disable recommendations", async () => {
    await page.route("**/api/cim/projects/*/workflow", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { message: "隔离网络失败测试" } }) }));
    await page.getByRole("button", { name: "刷新流程", exact: true }).click();
    await page.locator(".wf-error").filter({ hasText: "状态未刷新" }).waitFor();
    assert.ok(await page.locator(".wf-recommend button").isDisabled());
    await page.unroute("**/api/cim/projects/*/workflow");
    await page.getByRole("button", { name: "刷新流程", exact: true }).click(); await ready();
    assert.equal(await page.locator(".wf-error").count(), 0);
  });
  await check("1440 and 1024 layouts stay readable without horizontal overflow", async () => {
    await page.setViewportSize({ width: 1024, height: 1000 });
    await page.getByRole("button", { name: "定位当前节点", exact: true }).click();
    const canvas = await page.locator(".wf-canvas").boundingBox(), guide = await page.locator(".wf-guide").boundingBox();
    assert.ok(guide.y >= canvas.y + canvas.height - 1, "Guide moves under the canvas");
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
    await page.screenshot({ path: resolve(app, ".qa/screenshots/workflow-1024.png"), fullPage: true });
  });
  assert.deepEqual(errors, []);
  await writeFile(resolve(app, ".qa/workflow-browser-results.json"), JSON.stringify({ passed: tests, pageErrors: errors }, null, 2));
  console.log(JSON.stringify({ passed: tests.length, browser: "Edge headless", pageErrors: errors }));
} catch (error) {
  await page?.screenshot({ path: resolve(app, ".qa/screenshots/workflow-failure.png"), fullPage: true });
  if (page) await writeFile(resolve(app, ".qa/workflow-browser-failure.txt"), await page.locator("body").innerText());
  throw error;
} finally {
  await browser?.close(); server.kill();
  await writeFile(resolve(app, ".qa/workflow-browser-server.log"), log);
}
