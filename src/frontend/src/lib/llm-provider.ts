export type LLMProviderType = "openai" | "anthropic" | "google" | "openclaw" | "custom";

export interface LLMConfig {
  provider: LLMProviderType;
  apiKey: string;
  baseUrl?: string;
  model: string;
}

export const DEFAULT_MODELS: Record<LLMProviderType, string> = {
  openai: "gpt-4o",
  anthropic: "claude-sonnet-4-20250514",
  google: "gemini-2.0-flash",
  openclaw: "gpt-5-codex-mini",
  custom: "",
};

const LS_KEY = "growthmap_llm_config";

export function saveLLMConfig(config: LLMConfig): void {
  localStorage.setItem(LS_KEY, JSON.stringify(config));
}

export function loadLLMConfig(): LLMConfig | null {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as LLMConfig;
  } catch {
    return null;
  }
}

export async function llmComplete(
  config: LLMConfig,
  systemPrompt: string,
  userPrompt: string
): Promise<string> {
  const model = config.model || DEFAULT_MODELS[config.provider];

  switch (config.provider) {
    case "openai":
    case "openclaw":
    case "custom": {
      const baseUrl =
        config.provider === "openai"
          ? "https://api.openai.com/v1"
          : config.baseUrl?.replace(/\/$/, "");
      if (!baseUrl) throw new Error("需要設定 Base URL");

      const res = await fetch(`${baseUrl}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${config.apiKey}`,
        },
        body: JSON.stringify({
          model,
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: userPrompt },
          ],
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`LLM Error ${res.status}: ${text}`);
      }
      const data = await res.json();
      return data.choices?.[0]?.message?.content ?? "";
    }

    case "anthropic": {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": config.apiKey,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
        },
        body: JSON.stringify({
          model,
          max_tokens: 4096,
          system: systemPrompt,
          messages: [{ role: "user", content: userPrompt }],
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`LLM Error ${res.status}: ${text}`);
      }
      const data = await res.json();
      return data.content?.[0]?.text ?? "";
    }

    case "google": {
      const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${config.apiKey}`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [
            {
              parts: [{ text: `${systemPrompt}\n\n${userPrompt}` }],
            },
          ],
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`LLM Error ${res.status}: ${text}`);
      }
      const data = await res.json();
      return data.candidates?.[0]?.content?.parts?.[0]?.text ?? "";
    }

    default:
      throw new Error(`Unknown provider: ${config.provider}`);
  }
}

export function parseJsonResponse(raw: string): unknown {
  // Strip markdown code fences if present
  const cleaned = raw
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/i, "")
    .replace(/```\s*$/i, "")
    .trim();
  return JSON.parse(cleaned);
}
