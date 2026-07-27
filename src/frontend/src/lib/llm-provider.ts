export type LLMProviderType = "openai" | "anthropic" | "google" | "openclaw" | "custom" | "openai_compatible" | "mock";

/** Browser-safe provider selection. Secrets and endpoints are resolved by the backend. */
export interface LLMConfig {
  provider: LLMProviderType;
  providerId: string;
  model: string;
}

export const DEFAULT_MODELS: Record<LLMProviderType, string> = {
  openai: "gpt-4o",
  anthropic: "claude-sonnet-4-20250514",
  google: "gemini-2.0-flash",
  openclaw: "gpt-5-codex-mini",
  custom: "",
  openai_compatible: "",
  mock: "demo",
};

const LS_KEY = "growthmap_llm_config";

export function saveLLMConfig(config: LLMConfig): void {
  localStorage.setItem(LS_KEY, JSON.stringify({
    provider: config.provider,
    providerId: config.providerId,
    model: config.model,
  }));
}

export function loadLLMConfig(): LLMConfig | null {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return null;
    const candidate = value as Record<string, unknown>;
    if (typeof candidate.provider !== "string" || typeof candidate.providerId !== "string" || typeof candidate.model !== "string") return null;
    // Rewrite legacy records so previously persisted secret/endpoint fields are removed.
    const safe = { provider: candidate.provider as LLMProviderType, providerId: candidate.providerId, model: candidate.model };
    localStorage.setItem(LS_KEY, JSON.stringify(safe));
    return safe;
  } catch {
    return null;
  }
}
