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
  children?: GNode[];
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

export type Maturity = "seed" | "rough" | "developing" | "stable" | "finalized";

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
