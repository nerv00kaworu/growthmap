"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DEFAULT_MODELS, loadLLMConfig, saveLLMConfig, type LLMProviderType } from "@/lib/llm-provider";
import type { ProviderConfig } from "@/lib/types";

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
      <div className="w-full max-w-md space-y-4 rounded-xl border border-gray-700 bg-gray-900 p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-100">⚙️ LLM Provider 設定</h2>
            <p className="mt-1 text-xs text-gray-500">設定檔存本機資料庫；桌面密鑰由作業系統安全儲存保護。</p>
          </div>
          <button type="button" onClick={onClose} className="text-lg text-gray-500 hover:text-gray-300">×</button>
        </div>

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
