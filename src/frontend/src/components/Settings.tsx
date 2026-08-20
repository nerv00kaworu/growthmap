"use client";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { DEFAULT_MODELS, resolveAuthoritativeLLMConfig, type LLMProviderType } from "@/lib/llm-provider";
import { initialSettingsSaveState, reduceSettingsSave } from "@/lib/settings-save-state";
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
  const [saveState, setSaveState] = useState(initialSettingsSaveState);
  const selectedProfile=profiles.find(row=>row.id===selectedId);
  const pending=providerCredentialPending(selectedProfile);
  const loadProfiles = async (keepProviderId?: string) => {
    const rows = await api.listProviders();
    setProfiles(rows);
    const saved = resolveAuthoritativeLLMConfig(rows);
    if (keepProviderId && rows.some(row=>row.id===keepProviderId)) setSelectedId(keepProviderId);
    else if (saved) setSelectedId(saved.providerId);
    return rows;
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

  const refreshAfterCommittedSelection = async (providerId: string) => {
    try {
      await loadProfiles(providerId);
      setSaveState(state=>reduceSettingsSave(state,{type:"READBACK_OK"}));
      setMessage(u("✅ 設定已儲存並選用。","✅ 设置已保存并选用。","✅ Settings saved and selected."));
    } catch {
      setSaveState(state=>reduceSettingsSave(state,{type:"READBACK_FAIL"}));
      setMessage(u("✅ 已選用；清單刷新暫時失敗。","✅ 已选用；列表刷新暂时失败。","✅ Selected; the list refresh temporarily failed."));
    }
  };

  const refreshAndSelect = async (providerId: string) => {
    const rows=await loadProfiles(providerId);
    const revision=rows[0]?.selection_revision;
    if(!revision) throw new Error("Selection revision unavailable");
    setSaveState(state=>reduceSettingsSave(state,{type:"REFRESH_OK",selectionRevision:revision}));
    try {
      const committed=await api.setProviderSelection(providerId,revision);
      setSaveState(state=>reduceSettingsSave(state,{type:"SELECTION_COMMITTED",selectionRevision:committed.selection_revision}));
      await refreshAfterCommittedSelection(providerId);
    } catch(error: unknown) {
      const retryable=error instanceof ApiError && ["LLM_SELECTION_STALE","LLM_SELECTION_BUSY","LLM_SELECTION_UNAVAILABLE"].includes(error.code||"");
      if(retryable){
        const refreshed=await loadProfiles(providerId).catch(()=>[]);
        const latest=refreshed[0]?.selection_revision;
        if(latest) setSaveState(state=>reduceSettingsSave(state,{type:"SELECTION_RETRY",selectionRevision:latest}));
      }
      setMessage(retryable
        ? u("設定已保存，但目前未選用；請按選用重試。","设置已保存，但目前未选用；请按选用重试。","Settings were saved but are not selected. Select again to retry.")
        : u(`設定已保存，但選用失敗：${(error as Error).message}`,`设置已保存，但选用失败：${(error as Error).message}`,`Settings were saved, but selection failed: ${(error as Error).message}`));
    }
  };

  const retrySelection=async()=>{
    if(!saveState.providerId||!saveState.selectionRevision)return;
    setSaving(true);
    try{const committed=await api.setProviderSelection(saveState.providerId,saveState.selectionRevision);setSaveState(state=>reduceSettingsSave(state,{type:"SELECTION_COMMITTED",selectionRevision:committed.selection_revision}));await refreshAfterCommittedSelection(saveState.providerId)}
    catch(error: unknown){const retryable=error instanceof ApiError&&["LLM_SELECTION_STALE","LLM_SELECTION_BUSY","LLM_SELECTION_UNAVAILABLE"].includes(error.code||"");if(retryable){const rows=await loadProfiles(saveState.providerId).catch(()=>[]);const latest=rows[0]?.selection_revision;if(latest)setSaveState(state=>reduceSettingsSave(state,{type:"SELECTION_RETRY",selectionRevision:latest}))}setMessage(u("仍無法選用；請重試。","仍无法选用；请重试。","Selection is still unavailable. Retry."))}finally{setSaving(false)}
  };

  const saveProfile = async () => {
    if (!name.trim()) return;
    setSaving(true); setMessage(""); setSaveState(reduceSettingsSave(initialSettingsSaveState,{type:"START"}));
    const payload={name:name.trim(),provider_type:provider,endpoint:endpoint.trim(),secret_env_key:envKey.trim()||"GROWTHMAP_LLM_KEY_DEFAULT",model_name:model.trim()||DEFAULT_MODELS[provider],capabilities:["expand","deepen","chat"],cost_level:provider==="mock"?"none":"variable",enabled:true};
    let saved: ProviderConfig;
    try{saved=selectedId?await api.updateProvider(selectedId,payload):await api.createProvider(payload);setSaveState(state=>reduceSettingsSave(state,{type:"METADATA_OK",providerId:saved.id}));setSelectedId(saved.id);setProfiles(rows=>rows.some(row=>row.id===saved.id)?rows.map(row=>row.id===saved.id?saved:row):[saved,...rows])}
    catch(error){setSaveState(state=>reduceSettingsSave(state,{type:"METADATA_FAIL"}));setMessage(u(`Metadata 儲存失敗：${(error as Error).message}`,`Metadata 保存失败：${(error as Error).message}`,`Metadata save failed: ${(error as Error).message}`));setSaving(false);return}
    try{if(apiKey.trim()&&saved.provider_type!=="mock"){if(window.growthmapDesktop)await window.growthmapDesktop.secrets.set(saved.id,apiKey.trim());else await api.writeProviderSecret(saved.id,apiKey.trim());setApiKey("")}setSaveState(state=>reduceSettingsSave(state,{type:"SECRET_OK"}))}
    catch(error){setSaveState(state=>reduceSettingsSave(state,{type:"SECRET_FAIL"}));await loadProfiles(saved.id).catch(()=>undefined);setMessage(u(`Metadata 已保存，但憑證階段失敗：${(error as Error).message}；請依下方復原提示重試。`,`Metadata 已保存，但凭据阶段失败：${(error as Error).message}；请按下方恢复提示重试。`,`Metadata was saved, but the secret stage failed: ${(error as Error).message}. Use the recovery controls below.`));setSaving(false);return}
    try{await refreshAndSelect(saved.id)}catch(error){setMessage(u(`設定已保存，但清單刷新失敗：${(error as Error).message}`,`设置已保存，但列表刷新失败：${(error as Error).message}`,`Settings were saved, but profile refresh failed: ${(error as Error).message}`))}finally{setSaving(false)}
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
        {saveState.phase==="selection_retry"&&<button data-testid="retry-provider-selection" type="button" disabled={saving} onClick={retrySelection} className="w-full rounded-lg border border-amber-600 bg-amber-950/30 px-3 py-2 text-xs font-medium text-amber-100">{u("選用／重試","选用／重试","Select / Retry")}</button>}
        <div className="flex gap-2">
          <button type="button" onClick={createNew} className="rounded-lg border border-gray-600 px-3 py-2 text-xs text-gray-300 hover:text-white">{u('新增','新增','New')}</button>
          <button type="button" onClick={saveProfile} disabled={saving || pending || !name.trim()} className="flex-1 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50">{saving ? u("儲存中…", "保存中…", "Saving…") : u("儲存並使用", "保存并使用", "Save and use")}</button>
        </div>
      </div>
    </div>
  );
}
