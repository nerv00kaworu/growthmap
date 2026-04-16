"use client";

import type { GNode } from "@/lib/types";
import { api } from "@/lib/api";
import { useState } from "react";

const ACTION_LABELS: Record<string, string> = {
  create_node: "🌱 建立",
  update_node: "✏️ 編輯",
  create_project: "📁 建立專案",
  maturity_advance: "⬆️ 成熟度提升",
  ai_expand: "🤖 AI 展開",
  ai_deepen: "🤖 AI 深化",
};

interface NodeHistorySectionProps {
  selectedNode: GNode;
  Section: (props: { title: string; subtitle?: string; tone?: "neutral" | "ai" | "edit"; children: React.ReactNode }) => React.JSX.Element;
}

export function NodeHistorySection({ selectedNode, Section }: NodeHistorySectionProps) {
  const [history, setHistory] = useState<{ id: string; action_type: string; actor_type: string; payload: Record<string, unknown>; created_at: string }[]>([]);
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const h = await api.getHistory(selectedNode.id);
      setHistory(h);
      setShow(true);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Section title="操作紀錄" subtitle="回頭看這個節點怎麼長成現在這樣。">
      {!show ? (
        <div className="space-y-2">
          <button type="button" onClick={load} disabled={loading} className="text-sm text-gray-500 hover:text-gray-300 underline disabled:text-gray-600">
            {loading ? "⏳ 載入中..." : "📜 查看操作歷史"}
          </button>
          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>
      ) : (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <div className="text-sm text-gray-500 uppercase tracking-wider">📜 歷史</div>
            <button type="button" onClick={() => setShow(false)} className="text-sm text-gray-600 hover:text-gray-400">收起</button>
          </div>
          {history.length === 0 ? (
            <p className="text-sm text-gray-600">無記錄</p>
          ) : (
            history.map((h) => (
              <div key={h.id} className="text-xs text-gray-500 flex gap-2">
                <span className="text-gray-600 shrink-0">{h.created_at ? new Date(h.created_at).toLocaleString("zh-TW", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</span>
                <span>{ACTION_LABELS[h.action_type] || h.action_type}</span>
                {h.action_type === "maturity_advance" && h.payload && (
                  <span className="text-yellow-500">
                    {String(h.payload.from)} → {String(h.payload.to)}
                  </span>
                )}
                <span className="text-gray-700">({h.actor_type})</span>
              </div>
            ))
          )}
        </div>
      )}

      <div className="text-sm text-gray-600 space-y-1 pt-2 border-t border-gray-800">
        <div>ID: <span className="text-gray-500 font-mono">{selectedNode.id.slice(0, 8)}...</span></div>
        <div>建立: {new Date(selectedNode.created_at).toLocaleString("zh-TW")}</div>
        <div>更新: {new Date(selectedNode.updated_at).toLocaleString("zh-TW")}</div>
      </div>
    </Section>
  );
}
