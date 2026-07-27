// GrowthMap types — mirrors backend schemas
export interface GNode {
  id: string;
  project_id: string;
  title: string;
  summary: string;
  node_type: string;
  status: string;
  maturity: string;
  priority: number;
  confidence: number;
  description: string;
  rules_text: string;
  constraints_text: string;
  examples_text: string;
  questions_text: string;
  decision_notes: string;
  workflow_status: string;
  tags: string[];
  file_paths: string[];
  created_by: string;
  last_edited_by: string;
  position_x: number;
  position_y: number;
  meta: Record<string, unknown>;
  content_blocks: ContentBlock[];
  created_at: string;
  updated_at: string;
  ancestor_path?: LineageNode[];
  children?: GNode[];
  is_mainline?: boolean;
  branch_id?: string | null;
}

export type NodeFormalFieldKey =
  | "description"
  | "rules_text"
  | "constraints_text"
  | "examples_text"
  | "questions_text"
  | "decision_notes";

export type NodeEditDraft = Pick<
  GNode,
  NodeFormalFieldKey | "status" | "workflow_status" | "priority" | "confidence" | "file_paths"
>;

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
  project_id: string;
  from_node_id: string;
  to_node_id: string;
  relation_type: string;
  weight: number;
  note: string;
  is_mainline: boolean;
  created_at: string;
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

export interface AgentArtifact {
  id: string;
  session_id: string;
  project_id: string;
  target_node_id: string;
  artifact_type: "create_child" | "update_node" | "create_block";
  payload: Record<string, unknown>;
  status: "pending" | "applied" | "rejected";
  review_note: string;
  created_at: string;
  reviewed_at: string | null;
}

export type AgentSessionStatus = "idle" | "active" | "waiting_review" | "completed" | "cancelled";

export interface AgentSession {
  id: string;
  project_id: string;
  assigned_node_id: string | null;
  assigned_branch_root_id: string | null;
  provider_id: string | null;
  objective: string;
  mode: "one_shot" | "collab" | "background";
  status: AgentSessionStatus;
  handoff_context: Record<string, unknown>;
  result_summary: string;
  last_heartbeat_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderConfig {
  id: string;
  name: string;
  provider_type: string;
  endpoint: string;
  auth_type: string;
  secret_env_key: string;
  model_name: string;
  capabilities: string[];
  cost_level: string;
  enabled: boolean;
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

export interface BranchNodeSummary {
  id: string;
  title: string;
  summary: string;
  node_type: string;
  maturity: string;
  updated_at: string | null;
}

export interface BranchComparison {
  branch: Pick<Branch, "id" | "name" | "status">;
  source: BranchNodeSummary | null;
  branch_root: BranchNodeSummary | null;
  diff: {
    title_changed: boolean;
    summary_changed: boolean;
    maturity_changed: boolean;
    source_block_count: number;
    branch_block_count: number;
    branch_node_count: number;
  };
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
