"use client";

import type { GNode } from "@/lib/types";
import { api, type AgentPortActivity, type AgentPortReadback, type AgentPortRecord } from "@/lib/api";
import { freshNodeHistoryView, loadNodeHistory, NodeHistoryRequestCoordinator, visibleNodeHistoryView, type NodeHistoryViewState } from "@/lib/node-history-loader";
import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n/provider";
import { msg, dateLocale, activeMsg } from "@/i18n/ui";



interface NodeHistorySectionProps {
  selectedNode: GNode;
  Section: (props: { title: string; subtitle?: string; tone?: "neutral" | "ai" | "edit"; children: React.ReactNode }) => React.JSX.Element;
}

function StringList({ label, values }: { label: string; values: string[] }) {
  if (!values?.length) return null;
  return <div><div className="font-medium text-gray-400">{label}</div><ul className="list-disc space-y-0.5 pl-5">{values.map((value, index) => <li key={`${value}-${index}`} className="break-words">{value}</li>)}</ul></div>;
}

function RecordList({ label, values }: { label: string; values: AgentPortRecord[] }) {
  if (!values?.length) return null;
  return <div><div className="font-medium text-gray-400">{label}</div><ul className="space-y-1">{values.map((value, index) => <li key={`${value.name}-${index}`} className="rounded bg-black/20 px-2 py-1"><span className="text-gray-300">{value.name}</span>{value.status && <span className="ml-1 text-gray-500">· {value.status}</span>}{value.detail && <div className="whitespace-pre-wrap break-words text-gray-500">{value.detail}</div>}</li>)}</ul></div>;
}

function ImplementationTrace({ readback }: { readback: AgentPortReadback }) {
  const { locale } = useI18n();
  return <article data-testid="agent-implementation-trace" className="space-y-2 rounded-lg border border-purple-900/40 bg-purple-950/10 p-3 text-xs text-gray-400">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="font-semibold text-purple-200">{activeMsg({'zh-TW':'Agent 實作追蹤','zh-CN':'Agent 实现跟踪',en:'Agent implementation trace'})}</h4>
      <time className="text-gray-600">{readback.created_at ? new Date(readback.created_at).toLocaleString(dateLocale(locale)) : ""}</time>
    </div>
    {(readback.agent || readback.source || readback.revision !== undefined) && <div className="flex flex-wrap gap-x-3 gap-y-1 text-gray-500">
      {readback.agent && <span><b className="text-gray-400">Agent:</b> {readback.agent}</span>}
      {readback.source && <span><b className="text-gray-400">Source:</b> {readback.source}</span>}
      {readback.revision !== undefined && <span><b className="text-gray-400">Revision:</b> {readback.revision}</span>}
    </div>}
    {readback.summary && <div><div className="font-medium text-gray-400">Summary</div><p className="whitespace-pre-wrap break-words text-gray-300">{readback.summary}</p></div>}
    <StringList label="Commit refs" values={readback.commit_refs} />
    <StringList label="Files" values={readback.files} />
    <RecordList label="Tests" values={readback.tests} />
    <StringList label="Decisions" values={readback.decisions} />
    <StringList label="Risks" values={readback.risks} />
    <StringList label={activeMsg({'zh-TW':'待辦','zh-CN':'待办',en:'TODOs'})} values={readback.todos} />
    <RecordList label={activeMsg({'zh-TW':'證據','zh-CN':'证据',en:'Evidence'})} values={readback.evidence} />
  </article>;
}

type HistoryEntry = { id: string; action_type: string; actor_type: string; payload: Record<string, unknown>; created_at: string };
type HistoryView = NodeHistoryViewState<HistoryEntry, AgentPortReadback>;

export function NodeHistorySection({ selectedNode, Section }: NodeHistorySectionProps) {
  const { locale } = useI18n();
  const m = (tw:string,cn:string,en:string) => msg(locale,{"zh-TW":tw,"zh-CN":cn,en});
  const actionLabels: Record<string,string>={create_node:`🌱 ${m("建立","创建","Create")}`,update_node:`✏️ ${m("編輯","编辑","Edit")}`,create_project:`📁 ${m("建立專案","创建项目","Create project")}`,maturity_advance:`⬆️ ${m("成熟度提升","成熟度提升","Advance maturity")}`,ai_expand:`🤖 ${m("AI 展開","AI 展开","AI expand")}`,ai_deepen:`🤖 ${m("AI 深化","AI 深化","AI deepen")}`};
  const selectedNodeKey = `${selectedNode.project_id}:${selectedNode.id}`;
  const [storedView, setStoredView] = useState<HistoryView>(() => freshNodeHistoryView(selectedNodeKey));
  const view = visibleNodeHistoryView(storedView, selectedNodeKey);
  const {history,readbacks,show,loading,error,traceUnavailable} = view;
  const coordinator = useRef(new NodeHistoryRequestCoordinator(selectedNodeKey));

  useEffect(() => {
    // Invalidate old requests and never show one node's history under another.
    coordinator.current.select(selectedNodeKey);
    setStoredView(freshNodeHistoryView(selectedNodeKey));
  }, [selectedNode.id, selectedNode.project_id, selectedNodeKey]);

  const load = async () => {
    setStoredView({...freshNodeHistoryView<HistoryEntry,AgentPortReadback>(selectedNodeKey),loading:true});
    await loadNodeHistory<Awaited<ReturnType<typeof api.getHistory>>, AgentPortActivity>(
      coordinator.current,
      selectedNodeKey,
      () => api.getHistory(selectedNode.id),
      () => api.getAgentPortActivity(selectedNode.project_id, selectedNode.id),
      {
        onHistory: (h) => setStoredView((current) => current.selectionKey === selectedNodeKey ? {...current,history:h,show:true} : current),
        onActivity: (activity) => setStoredView((current) => current.selectionKey === selectedNodeKey ? {...current,readbacks:activity.readbacks} : current),
        onUnavailable: () => setStoredView((current) => current.selectionKey === selectedNodeKey ? {...current,readbacks:[],traceUnavailable:true} : current),
        onError: (e) => setStoredView((current) => current.selectionKey === selectedNodeKey ? {...current,error:(e as Error).message} : current),
        onSettled: () => setStoredView((current) => current.selectionKey === selectedNodeKey ? {...current,loading:false} : current),
      },
    );
  };

  return (
    <Section title={m("操作紀錄","操作记录","Activity")} subtitle={m("回頭看這個節點怎麼長成現在這樣。","查看此节点如何发展成现在的状态。","See how this node developed into its current state.")}>
      {!show ? (
        <div className="space-y-2">
          <button type="button" onClick={load} disabled={loading} className="text-sm text-gray-500 hover:text-gray-300 underline disabled:text-gray-600">
            {loading ? m("⏳ 載入中…","⏳ 加载中…","⏳ Loading…") : m("📜 查看操作歷史","📜 查看操作历史","📜 View activity history")}
          </button>
          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-sm text-gray-500 uppercase tracking-wider">📜 {m("歷史","历史","History")}</div>
            <button type="button" onClick={() => setStoredView((current) => current.selectionKey === selectedNodeKey ? {...current,show:false} : current)} className="text-sm text-gray-600 hover:text-gray-400"> {m("收起","收起","Collapse")}</button>
          </div>
          {history.length === 0 ? <p className="text-sm text-gray-600"> {m("無記錄","无记录","No records")}</p> : history.map((h) => (
            <div key={h.id} className="text-xs text-gray-500 flex gap-2">
              <span className="text-gray-600 shrink-0">{h.created_at ? new Date(h.created_at).toLocaleString(dateLocale(locale), { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</span>
              <span>{actionLabels[h.action_type] || h.action_type}</span>
              {h.action_type === "maturity_advance" && h.payload && <span className="text-yellow-500">{String(h.payload.from)} → {String(h.payload.to)}</span>}
              <span className="text-gray-700">({h.actor_type})</span>
            </div>
          ))}
          <div className="space-y-2 border-t border-gray-800 pt-3">
            <div className="text-sm uppercase tracking-wider text-purple-300">{activeMsg({'zh-TW':'Agent 實作追蹤','zh-CN':'Agent 实现跟踪',en:'Agent implementation trace'})}</div>
            {traceUnavailable ? <p data-testid="agent-trace-unavailable" className="text-xs text-gray-600">{m('Agent Port 人工控制目前無法使用。一般節點歷史仍可查看。','Agent Port 人工控制当前不可用。普通节点历史仍可查看。','Agent Port human control is unavailable. Normal node history remains available.')}</p> : readbacks.length === 0 ? <p className="text-xs text-gray-600">{m('此節點沒有 Agent 實作回報。','此节点没有 Agent 实现回报。','No Agent implementation readback for this node.')}</p> : readbacks.map((readback) => <ImplementationTrace key={readback.id} readback={readback} />)}
          </div>
        </div>
      )}

      <div className="text-sm text-gray-600 space-y-1 pt-2 border-t border-gray-800">
        <div>ID: <span className="text-gray-500 font-mono">{selectedNode.id.slice(0, 8)}...</span></div>
        <div>{m("建立","创建","Created")}: {new Date(selectedNode.created_at).toLocaleString(dateLocale(locale))}</div>
        <div>{m("更新","更新","Updated")}: {new Date(selectedNode.updated_at).toLocaleString(dateLocale(locale))}</div>
      </div>
    </Section>
  );
}
