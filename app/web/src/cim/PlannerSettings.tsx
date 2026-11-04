import { useEffect, useState } from "react";
import { plannerApi, type PlannerSettings as Settings } from "./planner-model";

export default function PlannerSettings({ csrf }: { csrf: string }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [key, setKey] = useState(""), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  useEffect(() => { let active = true; void plannerApi<Settings>(csrf, "planner/settings").then(value => { if (active) setSettings(value); }).catch(e => { if (active) setNotice(String(e)); }); return () => { active = false; }; }, [csrf]);
  async function save(clear = false) {
    if (!settings) return;
    setBusy(true); setNotice("");
    try {
      const { has_key: _hasKey, key_read_only: _keyReadOnly, agent: _agent, ...values } = settings;
      const result = await plannerApi<Settings>(csrf, "planner/settings", { ...values, ...(clear ? { clear_key: true } : key ? { api_key: key } : {}) });
      setSettings(result); setKey(""); setNotice(clear ? "API Key 已清除" : "配置已保存；实际请求结果将在创建向导中显示。");
    } catch (e) { setNotice(e instanceof Error ? e.message : "保存失败"); }
    finally { setBusy(false); }
  }
  return <details className="fc-surface pc-settings"><summary>项目规划 Agent · 模型连接与 API Key</summary>
    <p className="fc-muted">配置用于新建项目的需求对话和能力组合。后续专家任务按项目流程逐步执行与审查。</p>
    {!settings ? <p>{notice || "正在读取模型配置…"}</p> : <>
      <div className="fc-form-grid">
        <label className="fc-field"><span>模型提供方</span><select aria-label="规划模型提供方" value={settings.provider} onChange={e => {
          const provider = e.target.value as Settings["provider"]; setKey("");
          setSettings({ ...settings, provider, has_key: false, ...(provider === "deepseek" ? { base_url: "https://api.deepseek.com", model: "deepseek-flash", destination: "external" as const, internal_confirmed: false } : {}) });
        }}><option value="deepseek">DeepSeek 官方 API</option><option value="compatible">兼容接口 / 厂内部署</option></select></label>
        <label className="fc-field"><span>模型 ID</span><input aria-label="规划模型 ID" value={settings.model} onChange={e => setSettings({ ...settings, model: e.target.value })} /></label>
        <label className="fc-field"><span>API 地址</span><input aria-label="规划 API 地址" value={settings.base_url} readOnly={settings.provider === "deepseek"} onChange={e => { setKey(""); setSettings({ ...settings, base_url: e.target.value, has_key: false }); }} /></label>
        <label className="fc-field"><span>模型部署位置</span><select aria-label="规划模型部署位置" value={settings.destination} disabled={settings.provider === "deepseek"} onChange={e => setSettings({ ...settings, destination: e.target.value as Settings["destination"], internal_confirmed: false })}><option value="external">外部 API · 只发送 public 描述</option><option value="internal">厂内批准模型 · 允许已分级描述</option></select></label>
        <label className="fc-field"><span>API Key · {settings.has_key ? "已配置" : "尚未配置"}</span><input type="password" aria-label="项目规划 API Key" autoComplete="new-password" disabled={settings.key_read_only} value={key} placeholder={settings.key_read_only ? "由部署密钥文件提供" : settings.has_key ? "已保存，留空保留" : "在此输入 API Key"} onChange={e => setKey(e.target.value)} /></label>
      </div>
      {settings.destination === "internal" && <label className="pc-check"><input type="checkbox" checked={settings.internal_confirmed} onChange={e => setSettings({ ...settings, internal_confirmed: e.target.checked })} />我确认此地址及其实际调用的模型均为厂内批准部署</label>}
      <p className="fc-muted">{settings.key_read_only ? "Key 由部署密钥文件只读提供。更换或移除 Key 请更新宿主机文件并重新创建容器；此处可保存模型与接口设置。" : "Key 保存在本机 Windows 凭据管理器；界面、项目资料与任务包只显示是否配置。"}</p>
      <div className="fc-actions"><button type="button" disabled={busy} onClick={() => void save()}>保存规划 Agent 配置</button><button type="button" className="secondary" disabled={busy || !settings.has_key || settings.key_read_only} onClick={() => void save(true)}>清除规划 API Key</button><a href="https://api-docs.deepseek.com/" target="_blank" rel="noreferrer">DeepSeek 接口说明 ↗</a></div>
      {notice && <p role="status" className="pc-notice">{notice}</p>}
    </>}
  </details>;
}
