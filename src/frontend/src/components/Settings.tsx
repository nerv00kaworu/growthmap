"use client";

import { useState, useEffect } from "react";
import {
  loadLLMConfig,
  saveLLMConfig,
  llmComplete,
  DEFAULT_MODELS,
  type LLMConfig,
  type LLMProviderType,
} from "@/lib/llm-provider";

interface SettingsProps {
  onClose: () => void;
}

const PROVIDER_LABELS: Record<LLMProviderType, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google Gemini",
  openclaw: "OpenClaw",
  custom: "Custom",
};

export function Settings({ onClose }: SettingsProps) {
  const [provider, setProvider] = useState<LLMProviderType>("openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "ok" | "fail">("idle");
  const [testMsg, setTestMsg] = useState("");

  useEffect(() => {
    const saved = loadLLMConfig();
    if (saved) {
      setProvider(saved.provider);
      setApiKey(saved.apiKey);
      setBaseUrl(saved.baseUrl || "");
      setModel(saved.model || "");
    }
  }, []);

  const showBaseUrl = provider === "openclaw" || provider === "custom";

  const handleSave = () => {
    const config: LLMConfig = {
      provider,
      apiKey,
      baseUrl: showBaseUrl ? baseUrl : undefined,
      model: model || DEFAULT_MODELS[provider],
    };
    saveLLMConfig(config);
    onClose();
  };

  const handleTest = async () => {
    setTestStatus("testing");
    setTestMsg("");
    try {
      const config: LLMConfig = {
        provider,
        apiKey,
        baseUrl: showBaseUrl ? baseUrl : undefined,
        model: model || DEFAULT_MODELS[provider],
      };
      const result = await llmComplete(config, "你是一個助理。", "請回應「連線成功」四個字，不要加其他任何內容。");
      setTestStatus("ok");
      setTestMsg(`✅ 連線成功：${result.trim().slice(0, 50)}`);
    } catch (e: unknown) {
      setTestStatus("fail");
      setTestMsg(`❌ 連線失敗：${(e as Error).message}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-100">⚙️ LLM 設定</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 text-lg"
          >
            ×
          </button>
        </div>

        <div className="space-y-3">
          {/* Provider */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">Provider</label>
            <select
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value as LLMProviderType);
                setModel("");
              }}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100"
            >
              {(Object.keys(PROVIDER_LABELS) as LLMProviderType[]).map((p) => (
                <option key={p} value={p}>
                  {PROVIDER_LABELS[p]}
                </option>
              ))}
            </select>
          </div>

          {/* API Key */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600"
            />
          </div>

          {/* Base URL — only for openclaw/custom */}
          {showBaseUrl && (
            <div>
              <label className="block text-xs text-gray-400 mb-1">Base URL</label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://..."
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600"
              />
            </div>
          )}

          {/* Model override */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              模型（選填，預設：{DEFAULT_MODELS[provider] || "自訂"}）
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={DEFAULT_MODELS[provider] || "填入模型名稱"}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600"
            />
          </div>
        </div>

        {/* Test result */}
        {testMsg && (
          <div
            className={`text-xs rounded px-3 py-2 ${
              testStatus === "ok"
                ? "bg-green-900/40 text-green-300 border border-green-700/40"
                : "bg-red-900/40 text-red-300 border border-red-700/40"
            }`}
          >
            {testMsg}
          </div>
        )}

        {/* Buttons */}
        <div className="flex gap-2 pt-1">
          <button
            onClick={handleTest}
            disabled={testStatus === "testing" || !apiKey}
            className="flex-1 rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-xs text-gray-300 hover:text-gray-100 disabled:opacity-50"
          >
            {testStatus === "testing" ? "測試中..." : "🔌 測試連線"}
          </button>
          <button
            onClick={handleSave}
            disabled={!apiKey}
            className="flex-1 rounded-lg bg-blue-600 hover:bg-blue-500 px-3 py-2 text-xs text-white font-medium disabled:opacity-50"
          >
            儲存
          </button>
        </div>
      </div>
    </div>
  );
}
