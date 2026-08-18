"use client";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DEFAULT_MODELS, loadLLMConfig, saveLLMConfig, type LLMProviderType } from "@/lib/llm-provider";
import type { ProviderConfig } from "@/lib/types";
import { providerCredentialPending } from "@/lib/provider-pending";

interface SettingsProps {
  onClose: () => void;
}

const PROVIDER_LABELS: Record<LLMProviderType, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google Gemini",
  openclaw: "OpenClaw",
  custom: "Custom",
  openai_compatible: "OpenAI-compatible",
  mock: "Mock (Demo)",
};

export function Settings({ onClose }: SettingsProps) {
  const { locale } = useI18n();
  const u = useCallback((tw: string, cn: string, en: string) => msg(locale, {"zh-TW":tw,"zh-CN":cn,en}), [locale]);
  const [profiles, setProfiles] = useState<ProviderConfig[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<LLMProviderType>("openai_compatible");
  const [endpoint, setEndpoint] = useState("");
  const [envKey, setEnvKey] = useState("GROWTHMAP_LLM_KEY_DEFAULT");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const selectedProfile=profiles.find(row=>row.id===selectedId);
  const pending=providerCredentialPending(selectedProfile);
  const loadProfiles = async () => {
    const rows = await api.listProviders();
    setProfiles(rows);
    const saved = loadLLMConfig();
    if (saved?.providerId && rows.some((row) => row.id === saved.providerId)) {
      setSelectedId(saved.providerId);
    }
  };

  useEffect(() => {
    loadProfiles().catch((error: unknown) => setMessage(u(`讀取設定失敗：${(error as Error).message}`,`读取设置失败：${(error as Error).message}`,`Failed to load settings: ${(error as Error).message}`)));
  }, [u]);

  const selectProfile = (id: string) => {
    setSelectedId(id);
    const profile = profiles.find((row) => row.id === id);
    if (!profile) return;
    setName(profile.name);
    setProvider(profile.provider_type as LLMProviderType);
    setEndpoint(profile.endpoint || "");
    setEnvKey(profile.secret_env_key || "GROWTHMAP_LLM_KEY_DEFAULT");
    setModel(profile.model_name || "");
  };

  const saveProfile = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setMessage("");
    try {
      const payload = {
        name: name.trim(),
        provider_type: provider,
        endpoint: endpoint.trim(),
        secret_env_key: envKey.trim() || "GROWTHMAP_LLM_KEY_DEFAULT",
        model_name: model.trim() || DEFAULT_MODELS[provider],
        capabilities: ["expand", "deepen", "chat"],
        cost_level: provider === "mock" ? "none" : "variable",
        enabled: true,
      };
      const saved = selectedId
        ? await api.updateProvider(selectedId, payload)
        : await api.createProvider(payload);
      if (apiKey.trim() && saved.provider_type !== "mock") {
        if (window.growthmapDesktop) await window.growthmapDesktop.secrets.set(saved.id, apiKey.trim());
        else await api.writeProviderSecret(saved.id, apiKey.trim());
        setApiKey("");
      }
      // Secret publication advances the authoritative provider revision after
      // the metadata response. Never persist the pre-secret revision.
      const authoritative = apiKey.trim() && saved.provider_type !== "mock" ? await api.getProvider(saved.id) : saved;
      const nextProfiles = selectedId
        ? profiles.map((row) => row.id === authoritative.id ? authoritative : row)
        : [authoritative, ...profiles];
      setProfiles(nextProfiles);
      setSelectedId(authoritative.id);
      saveLLMConfig({ provider: authoritative.provider_type as LLMProviderType, providerId: authoritative.id, model: authoritative.model_name, revision: authoritative.revision });
      setMessage(window.growthmapDesktop ? u('✅ 已儲存。API key 由系統安全儲存保護，不會寫入資料庫、.env 或瀏覽器。','✅ 已保存。API key 由系统安全存储保护，不会写入数据库、.env 或浏览器。','✅ Saved. The API key is protected by secure system storage and never written to the database, .env, or browser.') : u('✅ 已儲存。Authoring 模式從本機 .env／環境變數讀取，不會寫進資料庫或瀏覽器。','✅ 已保存。Authoring 模式从本地 .env/环境变量读取，不会写入数据库或浏览器。','✅ Saved. Authoring mode reads local .env/environment variables and never writes them to the database or browser.'));
    } catch (error: unknown) {
      setMessage(u(`儲存失敗：${(error as Error).message}`,`保存失败：${(error as Error).message}`,`Save failed: ${(error as Error).message}`));
    } finally {
      setSaving(false);
    }
  };

  const recoverCredential=async(operation:"set"|"delete")=>{
    if(!selectedProfile)return;
    if(operation==="set"&&!apiKey.trim()){setMessage(u("請重新輸入 API key。","请重新输入 API key。","Re-enter the API key."));return}
    if(operation==="delete"&&!window.confirm(u("確認重試移除憑證？","确认重试移除凭据？","Retry credential removal?")))return;
    setSaving(true);setMessage("");
    try{await (window.growthmapDesktop?window.growthmapDesktop.secrets.recover(selectedProfile.id,selectedProfile.revision,operation,operation==="set"?apiKey.trim():undefined):api.recoverProviderSecret(selectedProfile.id,selectedProfile.revision,operation,operation==="set"?apiKey.trim():undefined));setApiKey("");await loadProfiles();setMessage(u("✅ 憑證更新已完成。","✅ 凭据更新已完成。","✅ Credential update completed."))}catch{setMessage(u("憑證更新仍未完成；請重新輸入 key 或重試移除。","凭据更新仍未完成；请重新输入 key 或重试移除。","Credential update is still incomplete; re-enter the key or retry removal."))}finally{setSaving(false)}
  };

  const createNew = () => {
    setSelectedId("");
    setName("");
    setProvider("openai_compatible");
    setEndpoint("");
    setEnvKey("GROWTHMAP_LLM_KEY_DEFAULT");
    setModel("");
    setApiKey("");
    setMessage("");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 backdrop-blur-sm">
      <div data-testid="llm-provider-settings" role="dialog" aria-modal="true" className="max-h-[90vh] w-full max-w-2xl space-y-4 overflow-y-auto rounded-xl border border-gray-700 bg-gray-900 p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-100">{u('⚙️ LLM Provider 設定','⚙️ LLM Provider 设置','⚙️ LLM provider settings')}</h2>
            <p className="mt-1 text-xs text-gray-500">{u('設定檔存本機資料庫；桌面密鑰由作業系統安全儲存保護。','配置保存在本地数据库；桌面密钥由操作系统安全存储保护。','Profiles are stored in the local database; desktop secrets are protected by secure operating-system storage.')}</p>
          </div>
          <button data-testid="llm-provider-settings-close" type="button" aria-label={u('關閉 LLM Provider 設定','关闭 LLM Provider 设置','Close LLM provider settings')} onClick={onClose} className="text-lg text-gray-500 hover:text-gray-300">×</button>
        </div>

        <div className="rounded-lg border border-emerald-800/40 bg-emerald-950/20 px-3 py-2 text-xs leading-5 text-emerald-200/80">
          {u('API key 不會出現在這個畫面、localStorage 或 SQLite。桌面版使用 Windows DPAPI／macOS Keychain；安全儲存不可用時會拒絕儲存。','API key 不会出现在此页面、localStorage 或 SQLite 中。桌面版使用 Windows DPAPI/macOS Keychain；安全存储不可用时将拒绝保存。','API keys never appear on this screen or in localStorage or SQLite. Desktop uses Windows DPAPI/macOS Keychain and refuses to save when secure storage is unavailable.')}
        </div>

        {profiles.length > 0 && (
          <label className="block text-xs text-gray-400">
            {u('已儲存 Provider','已保存 Provider','Saved providers')}
            <select value={selectedId} onChange={(event) => selectProfile(event.target.value)} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100">
              <option value="">{u('建立新的 Provider…','创建新的 Provider…','Create a new provider…')}</option>
              {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.enabled ? "●" : "○"} {profile.name} · {profile.model_name || profile.provider_type}</option>)}
            </select>
          </label>
        )}

        <div className="space-y-3">
          <label className="block text-xs text-gray-400">{u('顯示名稱','显示名称','Display name')}
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder={u("例：OpenAI 主要模型", "例：OpenAI 主模型", "e.g. Primary OpenAI model")} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100" />
          </label>
          <label className="block text-xs text-gray-400">Provider
            <select value={provider} onChange={(event) => setProvider(event.target.value as LLMProviderType)} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100">
              {(Object.keys(PROVIDER_LABELS) as LLMProviderType[]).map((value) => <option key={value} value={value}>{PROVIDER_LABELS[value]}</option>)}
            </select>
          </label>
          <label className="block text-xs text-gray-400">{u('Base URL（Mock 可留空）','Base URL（Mock 可留空）','Base URL (optional for Mock)')}
            <input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://api.openai.com/v1" className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100" />
          </label>
          <label className="block text-xs text-gray-400">{u('API key 的環境變數名稱','API key 环境变量名','API key environment-variable name')}
            <input value={envKey} onChange={(event) => setEnvKey(event.target.value)} placeholder="GROWTHMAP_LLM_KEY_DEFAULT" className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 font-mono text-sm text-gray-100" />
          </label>
          {provider !== "mock" && <label className="block text-xs text-gray-400">{u('API Key（桌面版使用系統安全儲存）','API Key（桌面版使用系统安全存储）','API key (desktop uses secure system storage)')}
            <input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={selectedId ? u("留空則維持現有 key", "留空则保留现有 key", "Leave blank to keep the existing key") : "sk-..."} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100" />
          </label>}
          <label className="block text-xs text-gray-400">{u('模型','模型','Model')}
            <input value={model} onChange={(event) => setModel(event.target.value)} placeholder={DEFAULT_MODELS[provider] || u('例：gpt-4o-mini','例：gpt-4o-mini','e.g. gpt-4o-mini')} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100" />
          </label>
        </div>

        {pending&&<div data-testid="credential-recovery" className="space-y-2 rounded border border-amber-700 bg-amber-950/40 px-3 py-2 text-xs text-amber-200"><div>{u("憑證更新未完成；請重新輸入 key 或重試移除。","凭据更新未完成；请重新输入 key 或重试移除。","Credential update is incomplete; re-enter the key or retry removal.")}</div><div className="flex gap-2"><button type="button" disabled={saving} onClick={()=>recoverCredential("set")} className="rounded bg-amber-700 px-2 py-1">{u("重新輸入並完成","重新输入并完成","Re-enter and recover")}</button><button type="button" disabled={saving} onClick={()=>recoverCredential("delete")} className="rounded border border-amber-700 px-2 py-1">{u("重試移除","重试移除","Retry removal")}</button></div></div>}
        {message && <div className="rounded border border-gray-700 bg-gray-800/70 px-3 py-2 text-xs text-gray-300">{message}</div>}
        <div className="flex gap-2">
          <button type="button" onClick={createNew} className="rounded-lg border border-gray-600 px-3 py-2 text-xs text-gray-300 hover:text-white">{u('新增','新增','New')}</button>
          <button type="button" onClick={saveProfile} disabled={saving || pending || !name.trim()} className="flex-1 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50">{saving ? u("儲存中…", "保存中…", "Saving…") : u("儲存並使用", "保存并使用", "Save and use")}</button>
        </div>
      </div>
    </div>
  );
}
