// GrowthMap types — mirrors backend schemas
export interface GNode {
  id: string;
  project_id: string;
  title: string;
  summary: string;
  node_type: string;
  status: string;
  maturity: string;
  tags: string[];
  meta: Record<string, unknown>;
  content_blocks: ContentBlock[];
  created_at: string;
  updated_at: string;
  ancestor_path?: LineageNode[];
  children?: GNode[];
  is_mainline?: boolean;
  branch_id?: string | null;
}

export interface LineageNode {
  id: string;
  title: string;
  node_type?: string;
}

export interface ContentBlock {
  id: string;
  node_id: string;
  block_type: string;
  content: Record<string, string>;
  order_index: number;
}

export interface Edge {
  id: string;
  source_id: string;
  target_id: string;
  relation: string;
  meta: Record<string, unknown>;
  is_mainline?: boolean;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  goal: string;
  root_node_id: string;
  status: string;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Branch {
  id: string;
  project_id: string;
  name: string;
  description: string;
  source_node_id: string;
  status: string;
  created_at: string;
}

export interface Suggestion {
  title: string;
  summary: string;
  node_type: string;
}

export interface DeepenResult {
  enriched_summary: string;
  content_blocks: { title: string; body: string; block_type: string }[];
  target_node_id: string;
}

export type Maturity = "seed" | "rough" | "developing" | "stable" | "finalized";

export type GrowthMode = "focused" | "explore" | "challenge";

export const GROWTH_MODE_LABELS: Record<GrowthMode, string> = {
  focused: "聚焦主線",
  explore: "探索延伸",
  challenge: "挑戰假設",
};

export const GROWTH_MODE_HELP: Record<GrowthMode, string> = {
  focused: "補齊當前主線缺口，避免一次跳太遠。",
  explore: "沿著主題向相鄰空間擴張，減少結果過早定型。",
  challenge: "主動提出反例、風險與替代方向，打破僵硬分支。",
};

export const MATURITY_COLORS: Record<Maturity, string> = {
  seed: "#a78bfa",
  rough: "#f59e0b",
  developing: "#3b82f6",
  stable: "#10b981",
  finalized: "#6366f1",
};

export const MATURITY_LABELS: Record<Maturity, string> = {
  seed: "🌱 種子",
  rough: "🪨 粗胚",
  developing: "🔧 發展中",
  stable: "✅ 穩定",
  finalized: "🔒 定稿",
};

export const NODE_TYPE_ICONS: Record<string, string> = {
  idea: "💡",
  concept: "🧠",
  task: "📋",
  question: "❓",
  decision: "⚖️",
  risk: "⚠️",
  resource: "📦",
  note: "📝",
  module: "🔧",
};
