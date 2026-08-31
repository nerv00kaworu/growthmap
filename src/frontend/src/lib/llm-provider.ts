export type LLMProviderType = "openai" | "anthropic" | "google" | "openclaw" | "custom" | "openai_compatible" | "mock";

/** Browser-safe provider selection. Secrets and endpoints are resolved by the backend. */
export interface LLMConfig {
  provider: LLMProviderType;
  providerId: string;
  model: string;
  revision: number;
  selectionRevision: number;
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

export const LLM_CONFIG_CHANGED_EVENT = "growthmap:llm-config-changed";

const LS_KEY = "growthmap_llm_config";

export function sameLLMConfig(a: LLMConfig | null, b: LLMConfig | null): boolean {
  return !!(a && b && a.provider === b.provider && a.providerId === b.providerId && a.model === b.model && a.revision === b.revision && a.selectionRevision === b.selectionRevision);
}

function parseStoredLLMConfig(raw: string | null): { config: LLMConfig; canonical: string } | null {
  if (!raw) return null;
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.provider !== "string" || typeof candidate.providerId !== "string" || typeof candidate.model !== "string" || typeof candidate.revision !== "number" || !Number.isInteger(candidate.revision) || candidate.revision < 1 || typeof candidate.selectionRevision !== "number" || !Number.isSafeInteger(candidate.selectionRevision) || candidate.selectionRevision < 1) return null;
  const config = { provider: candidate.provider as LLMProviderType, providerId: candidate.providerId, model: candidate.model, revision: candidate.revision, selectionRevision: candidate.selectionRevision };
  return { config, canonical: JSON.stringify(config) };
}

export function saveLLMConfig(config: LLMConfig): boolean {
  const safe = {
    provider: config.provider,
    providerId: config.providerId,
    model: config.model,
    revision: config.revision,
    selectionRevision: config.selectionRevision,
  };
  const canonical = JSON.stringify(safe);
  try {
    const raw = localStorage.getItem(LS_KEY);
    const stored = parseStoredLLMConfig(raw);
    if (sameLLMConfig(stored?.config ?? null, safe)) {
      // Preserve exact-match idempotence while still stripping extra legacy fields.
      if (raw !== canonical) localStorage.setItem(LS_KEY, canonical);
      return false;
    }
  } catch {
    // Fall through to the existing write path; storage failures remain caller-visible.
  }
  localStorage.setItem(LS_KEY, canonical);
  window.dispatchEvent(new CustomEvent(LLM_CONFIG_CHANGED_EVENT, { detail: { providerId: config.providerId } }));
  return true;
}

export function loadLLMConfig(): LLMConfig | null {
  try {
    const raw = localStorage.getItem(LS_KEY);
    const stored = parseStoredLLMConfig(raw);
    if (!stored) return null;
    // Rewrite only valid noncanonical records so previously persisted extra fields are removed.
    if (raw !== stored.canonical) localStorage.setItem(LS_KEY, stored.canonical);
    return stored.config;
  } catch {
    return null;
  }
}


export function configFromProvider(p: {id:string;provider_type:string;model_name:string;revision:number;selection_revision?:number}): LLMConfig {
  return {provider:p.provider_type as LLMProviderType,providerId:p.id,model:p.model_name,revision:p.revision,selectionRevision:p.selection_revision ?? 1};
}

/** Backend default is authoritative; localStorage is only a same-origin warm cache. */
export function resolveAuthoritativeLLMConfig<T extends {id:string;provider_type:string;model_name:string;revision:number;enabled:boolean;is_default?:boolean;selection_revision?:number}>(profiles: readonly T[]): LLMConfig | null {
  const enabled=profiles.filter(p=>p.enabled);
  const authoritative=enabled.find(p=>p.is_default);
  if(authoritative)return configFromProvider(authoritative);
  return null;
}
