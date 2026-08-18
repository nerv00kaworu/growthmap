// Mirrors backend models/content_blocks.py at the TypeScript language boundary.
export const CONTENT_BLOCK_TYPES = [
  "paragraph","bullet_list","rule_set","example","risk_note","decision_log",
  "todo","prompt_context","code","quote","table","text","markdown","note",
  "question","task","decision","risk","resource","definition","rules","spec",
] as const;
export type ContentBlockType = typeof CONTENT_BLOCK_TYPES[number];
