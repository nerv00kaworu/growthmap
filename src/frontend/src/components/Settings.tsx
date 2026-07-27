"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DEFAULT_MODELS, loadLLMConfig, saveLLMConfig, type LLMProviderType } from "@/lib/llm-provider";
import type { ProviderConfig } from "@/lib/types";
import type { DesktopBackup, DesktopDatabaseStatus } from "@/desktop";

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
  const [database, setDatabase] = useState<DesktopDatabaseStatus | null>(null);
  const [backups, setBackups] = useState<DesktopBackup[]>([]);
  const [databaseBusy, setDatabaseBusy] = useState(false);

  const refreshDatabase = async () => {
    if (!window.growthmapDesktop) return;
    const [status, rows] = await Promise.all([window.growthmapDesktop.database.status(), window.growthmapDesktop.database.listBackups()]);
    setDatabase(status); setBackups(rows);
  };

  const databaseAction = async (action: "backup" | "import" | "restore", backup?: DesktopBackup) => {
    const desktop = window.growthmapDesktop;
    if (!desktop) return;
    if (action !== "backup" && !confirm(action === "import" ? "匯入會先自動備份，然後以選取的資料庫取代目前本機資料並重啟。確定繼續？" : `還原此備份會先自動備份目前資料並重啟（${backup?.projects ?? 0} 個專案）。確定繼續？`)) return;
    setDatabaseBusy(true); setMessage("");
    try {
      const result = action === "backup" ? await desktop.database.backup() : action === "import" ? await desktop.database.import() : await desktop.database.restore(backup!.id);
      if (result) setMessage(action === "backup" ? "✅ 備份完成。" : "✅ 資料庫已安全替換並重新載入。");
      await refreshDatabase();
    } catch { setMessage("資料庫操作失敗；原有資料未變更。"); }
    finally { setDatabaseBusy(false); }
  };

  const loadProfiles = async () => {
    const rows = await api.listProviders();
    setProfiles(rows);
    const saved = loadLLMConfig();
    if (saved?.providerId && rows.some((row) => row.id === saved.providerId)) {
      setSelectedId(saved.providerId);
    }
  };

  useEffect(() => {
    loadProfiles().catch((error: unknown) => setMessage(`讀取設定失敗：${(error as Error).message}`));
    refreshDatabase().catch(() => setMessage("無法讀取資料庫狀態。"));
  }, []);

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
      const nextProfiles = selectedId
        ? profiles.map((row) => row.id === saved.id ? saved : row)
        : [saved, ...profiles];
      setProfiles(nextProfiles);
      setSelectedId(saved.id);
      saveLLMConfig({ provider: saved.provider_type as LLMProviderType, providerId: saved.id, model: saved.model_name });
      setMessage(window.growthmapDesktop ? "✅ 已儲存。API key 由系統安全儲存保護，不會寫入資料庫、.env 或瀏覽器。" : "✅ 已儲存。Authoring 模式從本機 .env／環境變數讀取，不會寫進資料庫或瀏覽器。");
    } catch (error: unknown) {
      setMessage(`儲存失敗：${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
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
      <div className="max-h-[90vh] w-full max-w-2xl space-y-4 overflow-y-auto rounded-xl border border-gray-700 bg-gray-900 p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-100">⚙️ LLM Provider 設定</h2>
            <p className="mt-1 text-xs text-gray-500">設定檔存本機資料庫；桌面密鑰由作業系統安全儲存保護。</p>
          </div>
          <button type="button" onClick={onClose} className="text-lg text-gray-500 hover:text-gray-300">×</button>
        </div>

        {window.growthmapDesktop && <section data-testid="database-management" className="space-y-3 rounded-lg border border-blue-800/40 bg-blue-950/20 p-4">
          <div><h3 className="text-sm font-semibold text-blue-100">資料管理</h3><p className="mt-1 text-xs text-blue-200/60">資料庫操作期間服務會暫停；匯入與還原只會取代，不會合併。</p></div>
          {database && <div className="grid grid-cols-2 gap-2 text-xs text-gray-300"><span>目前：{database.basename}</span><span>{database.projects} 個專案</span><span>{(database.size/1024).toFixed(1)} KB</span><span>最近備份：{database.lastBackup ? new Date(database.lastBackup).toLocaleString() : "尚無"}</span></div>}
          <div className="flex flex-wrap gap-2"><button data-testid="database-backup" disabled={databaseBusy} onClick={() => databaseAction("backup")} className="rounded bg-blue-700 px-3 py-2 text-xs text-white disabled:opacity-50">立即備份</button><button data-testid="database-import" disabled={databaseBusy} onClick={() => databaseAction("import")} className="rounded border border-amber-700 px-3 py-2 text-xs text-amber-200 disabled:opacity-50">匯入既有 DB</button><button disabled={databaseBusy} onClick={() => window.growthmapDesktop?.database.revealFolder()} className="rounded border border-gray-600 px-3 py-2 text-xs text-gray-300">開啟備份資料夾</button></div>
          <div className="max-h-36 space-y-2 overflow-y-auto">{backups.length === 0 ? <p className="text-xs text-gray-500">尚無 app 管理的備份。</p> : backups.map((item) => <div key={item.id} className="flex items-center justify-between rounded border border-gray-800 bg-gray-950/40 p-2 text-xs"><div><div>{new Date(item.createdAt).toLocaleString()} · {item.projects} 個專案 · {(item.size/1024).toFixed(1)} KB</div><div className="font-mono text-[10px] text-gray-600">SHA-256 {item.sha256.slice(0,16)}…</div></div><button data-testid="database-restore" disabled={databaseBusy} onClick={() => databaseAction("restore", item)} className="rounded border border-red-800 px-2 py-1 text-red-300 disabled:opacity-50">還原</button></div>)}</div>
          {databaseBusy && <div className="text-xs text-blue-200">處理中，請勿關閉應用程式…</div>}
        </section>}

        <div className="rounded-lg border border-emerald-800/40 bg-emerald-950/20 px-3 py-2 text-xs leading-5 text-emerald-200/80">
          API key 不會出現在這個畫面、localStorage 或 SQLite。桌面版使用 Windows DPAPI／macOS Keychain；安全儲存不可用時會拒絕儲存。
        </div>

        {profiles.length > 0 && (
          <label className="block text-xs text-gray-400">
            已儲存 Provider
            <select value={selectedId} onChange={(event) => selectProfile(event.target.value)} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100">
              <option value="">建立新的 Provider…</option>
              {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.enabled ? "●" : "○"} {profile.name} · {profile.model_name || profile.provider_type}</option>)}
            </select>
          </label>
        )}

        <div className="space-y-3">
          <label className="block text-xs text-gray-400">顯示名稱
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例：OpenAI 主要模型" className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100" />
          </label>
          <label className="block text-xs text-gray-400">Provider
            <select value={provider} onChange={(event) => setProvider(event.target.value as LLMProviderType)} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100">
              {(Object.keys(PROVIDER_LABELS) as LLMProviderType[]).map((value) => <option key={value} value={value}>{PROVIDER_LABELS[value]}</option>)}
            </select>
          </label>
          <label className="block text-xs text-gray-400">Base URL（Mock 可留空）
            <input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://api.openai.com/v1" className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100" />
          </label>
          <label className="block text-xs text-gray-400">API key 的環境變數名稱
            <input value={envKey} onChange={(event) => setEnvKey(event.target.value)} placeholder="GROWTHMAP_LLM_KEY_DEFAULT" className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 font-mono text-sm text-gray-100" />
          </label>
          {provider !== "mock" && <label className="block text-xs text-gray-400">API Key（桌面版使用系統安全儲存）
            <input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={selectedId ? "留空則維持現有 key" : "sk-..."} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100" />
          </label>}
          <label className="block text-xs text-gray-400">模型
            <input value={model} onChange={(event) => setModel(event.target.value)} placeholder={DEFAULT_MODELS[provider] || "例：gpt-4o-mini"} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100" />
          </label>
        </div>

        {message && <div className="rounded border border-gray-700 bg-gray-800/70 px-3 py-2 text-xs text-gray-300">{message}</div>}
        <div className="flex gap-2">
          <button type="button" onClick={createNew} className="rounded-lg border border-gray-600 px-3 py-2 text-xs text-gray-300 hover:text-white">新增</button>
          <button type="button" onClick={saveProfile} disabled={saving || !name.trim()} className="flex-1 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50">{saving ? "儲存中…" : "儲存並使用"}</button>
        </div>
      </div>
    </div>
  );
}
