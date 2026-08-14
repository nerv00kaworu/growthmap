"use client";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AgentArtifact, AgentSession, AgentSessionStatus, Branch, GNode, ProviderConfig } from "@/lib/types";

interface Props {
  projectId: string;
  rootNode: GNode;
  branches: Branch[];
  onClose: () => void;
}



const flatten = (node: GNode): GNode[] => [node, ...(node.children || []).flatMap(flatten)];

export function AgentSessions({ projectId, rootNode, branches, onClose }: Props) {
  const { locale } = useI18n();
  const u = useCallback((tw: string, cn: string, en: string) => msg(locale, {"zh-TW":tw,"zh-CN":cn,en}), [locale]);
  const STATUS_LABEL: Record<AgentSessionStatus,string> = {idle:u('待開始','待开始','Not started'),active:u('進行中','进行中','Active'),waiting_review:u('待審核','待审核','Awaiting review'),completed:u('已完成','已完成','Completed'),cancelled:u('已取消','已取消','Cancelled')};
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [branchTargets, setBranchTargets] = useState<{ id: string; label: string }[]>([]);
  const [filter, setFilter] = useState<AgentSessionStatus | "">("");
  const [objective, setObjective] = useState("");
  const [mode, setMode] = useState<AgentSession["mode"]>("one_shot");
  const [scope, setScope] = useState<"node" | "branch">("node");
  const [targetId, setTargetId] = useState(rootNode.id);
  const [providerId, setProviderId] = useState("");
  const [result, setResult] = useState<Record<string, string>>({});
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [artifacts, setArtifacts] = useState<AgentArtifact[]>([]);
  const [artifactTitle, setArtifactTitle] = useState("");
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const nodeTargets = flatten(rootNode);

  const reload = useCallback(async () => {
    setBusy(true);
    try { setSessions(await api.listAgentSessions(projectId, filter || undefined)); }
    catch (error: unknown) { setMessage(u(`讀取失敗：${(error as Error).message}`,`读取失败：${(error as Error).message}`,`Load failed: ${(error as Error).message}`)); }
    finally { setBusy(false); }
  }, [projectId, filter, u]);
  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    api.listProviders().then(setProviders).catch(() => undefined);
    Promise.all(branches.filter((branch) => branch.status === "active").map(async (branch) => {
      const subtree = await api.getBranchSubtree(branch.id);
      return subtree.tree ? { id: subtree.tree.id, label: u(`方案線：${branch.name}`,`方案线：${branch.name}`,`Scenario: ${branch.name}`) } : null;
    })).then((rows) => setBranchTargets(rows.filter((row): row is { id: string; label: string } => row !== null))).catch(() => setBranchTargets([]));
  }, [branches, u]);

  const create = async () => {
    if (!objective.trim()) return;
    setBusy(true); setMessage("");
    try {
      await api.createAgentSession({
        project_id: projectId, objective: objective.trim(), mode,
        provider_id: providerId || undefined,
        assigned_node_id: scope === "node" ? targetId : undefined,
        assigned_branch_root_id: scope === "branch" ? targetId : undefined,
      });
      setObjective(""); setMessage(u('✅ 工作階段已建立；這只是人工協作追蹤，不會自動呼叫模型。','✅ 工作阶段已创建；这仅用于人工协作跟踪，不会自动调用模型。','✅ Session created. This tracks human collaboration only and does not call a model automatically.'));
      await reload();
    } catch (error: unknown) { setMessage(u(`建立失敗：${(error as Error).message}`,`创建失败：${(error as Error).message}`,`Create failed: ${(error as Error).message}`)); setBusy(false); }
  };

  const update = async (session: AgentSession, status: AgentSessionStatus) => {
    setBusy(true); setMessage("");
    try {
      await api.updateAgentSession(session.id, { status, result_summary: result[session.id] || undefined });
      await reload();
    } catch (error: unknown) { setMessage(u(`更新失敗：${(error as Error).message}`,`更新失败：${(error as Error).message}`,`Update failed: ${(error as Error).message}`)); setBusy(false); }
  };

  const selectedSession = sessions.find((session) => session.id === selectedSessionId) || null;
  const loadArtifacts = async (sessionId: string) => {
    setSelectedSessionId(sessionId); setBusy(true);
    try { setArtifacts(await api.listAgentArtifacts(sessionId)); }
    catch (error: unknown) { setMessage(u(`讀取產物失敗：${(error as Error).message}`,`读取产物失败：${(error as Error).message}`,`Failed to load artifacts: ${(error as Error).message}`)); }
    finally { setBusy(false); }
  };
  const proposeChild = async () => {
    if (!selectedSession || !artifactTitle.trim()) return;
    const targetNodeId = selectedSession.assigned_node_id || selectedSession.assigned_branch_root_id;
    if (!targetNodeId) return;
    setBusy(true); setMessage("");
    try {
      await api.createAgentArtifact(selectedSession.id, { target_node_id: targetNodeId, artifact_type: "create_child", payload: { title: artifactTitle.trim() } });
      setArtifactTitle(""); await loadArtifacts(selectedSession.id);
    } catch (error: unknown) { setMessage(u(`提出產物失敗：${(error as Error).message}`,`提出产物失败：${(error as Error).message}`,`Failed to propose artifact: ${(error as Error).message}`)); setBusy(false); }
  };
  const reviewArtifact = async (artifact: AgentArtifact, action: "approve" | "reject") => {
    setBusy(true); setMessage("");
    try {
      if (action === "approve") await api.approveAgentArtifact(artifact.id, artifact.target_node_id, reviewNotes[artifact.id] || "");
      else await api.rejectAgentArtifact(artifact.id, reviewNotes[artifact.id] || "");
      if (selectedSession) await loadArtifacts(selectedSession.id);
    } catch (error: unknown) { setMessage(u(`審核失敗：${(error as Error).message}`,`审核失败：${(error as Error).message}`,`Review failed: ${(error as Error).message}`)); setBusy(false); }
  };

  const targetOptions = scope === "node"
    ? nodeTargets.map((node) => ({ id: node.id, label: node.title }))
    : branchTargets;

  return <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 px-4" onClick={onClose}>
    <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-gray-700 bg-gray-900 p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
      <div className="flex items-start justify-between"><div><h2 className="text-sm font-semibold text-gray-100">{u('🤖 Agent 工作階段','🤖 Agent 工作阶段','🤖 Agent sessions')}</h2><p className="mt-1 text-xs text-gray-500">{u('記錄委派、進度與人工審核；此版本不會自動送出任何外部任務或 LLM 呼叫。','记录委派、进度与人工审核；此版本不会自动发送任何外部任务或 LLM 调用。','Track delegation, progress, and human review. This version never sends external tasks or LLM calls automatically.')}</p></div><button type="button" onClick={onClose} className="text-lg text-gray-500 hover:text-gray-300">×</button></div>
      <div className="mt-4 grid gap-3 rounded-lg border border-gray-800 bg-gray-950/40 p-3 sm:grid-cols-2">
        <label className="text-xs text-gray-400 sm:col-span-2">{u('工作目標','工作目标','Objective')}<textarea value={objective} onChange={(event) => setObjective(event.target.value)} placeholder={u('例：審查此節點的技術風險，整理成可審核的建議。','例：审查此节点的技术风险，整理为可审核的建议。','e.g. Review this node’s technical risks and prepare an actionable recommendation.')}  className="mt-1 min-h-16 w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100" /></label>
        <label className="text-xs text-gray-400">{u('範圍','范围','Scope')}<select value={scope} onChange={(event) => { setScope(event.target.value as "node" | "branch"); setTargetId(event.target.value === "node" ? rootNode.id : ""); }} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-2 text-sm text-gray-100"><option value="node">{u('節點','节点','Nodes')}</option><option value="branch">{u('方案線根節點','方案线根节点','Scenario root node')}</option></select></label>
        <label className="text-xs text-gray-400">{u('目標','目标','Target')}<select value={targetId} onChange={(event) => setTargetId(event.target.value)} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-2 text-sm text-gray-100"><option value="">{u('選擇目標…','选择目标…','Select a target…')}</option>{targetOptions.map((target) => <option key={target.id} value={target.id}>{target.label}</option>)}</select></label>
        <label className="text-xs text-gray-400">{u('工作模式','工作模式','Mode')}<select value={mode} onChange={(event) => setMode(event.target.value as AgentSession["mode"])} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-2 text-sm text-gray-100"><option value="one_shot">{u('一次性','一次性','One-shot')}</option><option value="collab">{u('協作','协作','Collaboration')}</option><option value="background">{u('背景追蹤','后台跟踪','Background tracking')}</option></select></label>
        <label className="text-xs text-gray-400">{u('Provider（選填）','Provider（可选）','Provider (optional)')}<select value={providerId} onChange={(event) => setProviderId(event.target.value)} className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-2 text-sm text-gray-100"><option value="">{u('不指定','不指定','Unspecified')}</option>{providers.filter((provider) => provider.enabled).map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</select></label>
        <button type="button" disabled={busy || !objective.trim() || !targetId} onClick={create} className="rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-500 disabled:opacity-50 sm:col-span-2">{u('建立人工工作階段','创建人工工作阶段','Create manual session')}</button>
      </div>
      {message && <div className="mt-3 rounded border border-gray-700 bg-gray-800 px-3 py-2 text-xs text-gray-300">{message}</div>}
      <div className="mt-5 flex items-center justify-between"><h3 className="text-sm font-medium text-gray-200">{u('工作階段','工作阶段','Sessions')}</h3><select value={filter} onChange={(event) => setFilter(event.target.value as AgentSessionStatus | "")} className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-300"><option value="">{u('全部狀態','全部状态','All statuses')}</option>{Object.entries(STATUS_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
      <div className="mt-2 space-y-2">{busy && sessions.length === 0 ? <div className="py-6 text-center text-sm text-gray-500">{u('讀取中…','加载中…','Loading…')}</div> : sessions.length === 0 ? <div className="py-6 text-center text-sm text-gray-500">{u('尚無工作階段。','暂无工作阶段。','No sessions yet.')}</div> : sessions.map((session) => <div key={session.id} className="rounded-lg border border-gray-800 bg-gray-950/40 p-3"><div className="flex items-start justify-between gap-3"><div><div className="text-sm text-gray-200">{session.objective}</div><div className="mt-1 text-xs text-gray-500">{session.mode} · {STATUS_LABEL[session.status]} · {new Date(session.updated_at).toLocaleString(locale)}</div></div><div className="flex items-center gap-2"><button type="button" onClick={() => loadArtifacts(session.id)} className="rounded border border-purple-800/60 px-2 py-1 text-xs text-purple-200">{u('產物審核','产物审核','Review artifacts')}</button><span className="rounded bg-gray-800 px-2 py-1 text-xs text-gray-400">{STATUS_LABEL[session.status]}</span></div></div>{["waiting_review", "completed", "cancelled"].includes(session.status) && <textarea value={result[session.id] ?? session.result_summary} onChange={(event) => setResult({ ...result, [session.id]: event.target.value })} placeholder={u("填寫結果／結案摘要", "填写结果/结案摘要", "Enter result / closing summary")} className="mt-2 min-h-14 w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200" />}{session.status === "idle" && <button type="button" onClick={() => update(session, "active")} className="mt-2 rounded border border-blue-700 px-2 py-1 text-xs text-blue-300">{u('開始追蹤','开始跟踪','Start tracking')}</button>}{session.status === "active" && <div className="mt-2 flex gap-2"><button type="button" onClick={() => update(session, "waiting_review")} className="rounded border border-amber-700 px-2 py-1 text-xs text-amber-300">{u('送審','提交审核','Submit for review')}</button><button type="button" onClick={() => update(session, "completed")} className="rounded border border-emerald-700 px-2 py-1 text-xs text-emerald-300">{u('標記完成','标记完成','Mark complete')}</button><button type="button" onClick={() => update(session, "cancelled")} className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-400">{u('取消','取消','Cancel')}</button></div>}{session.status === "waiting_review" && <div className="mt-2 flex gap-2"><button type="button" onClick={() => update(session, "completed")} className="rounded border border-emerald-700 px-2 py-1 text-xs text-emerald-300">{u('核准完成','批准完成','Approve completion')}</button><button type="button" onClick={() => update(session, "active")} className="rounded border border-blue-700 px-2 py-1 text-xs text-blue-300">{u('退回進行中','退回进行中','Return to active')}</button></div>}</div>)}</div>
      {selectedSession && <div className="mt-4 rounded-lg border border-purple-800/50 bg-purple-950/10 p-3"><div className="flex items-center justify-between"><div><div className="text-sm font-medium text-purple-100">{u('審核產物：','审核产物：','Review artifacts: ')}{selectedSession.objective}</div><div className="text-xs text-purple-200/60">{u('產物必須先核准，才會寫入專案。','产物必须先获批准，才会写入项目。','Artifacts must be approved before they are written to the project.')}</div></div><button type="button" onClick={() => { setSelectedSessionId(""); setArtifacts([]); }} className="text-xs text-gray-500">{u('關閉','关闭','Close')}</button></div>{["active", "waiting_review"].includes(selectedSession.status) && <div className="mt-3 flex gap-2"><input value={artifactTitle} onChange={(event) => setArtifactTitle(event.target.value)} placeholder={u('提出一個待核准的子節點標題','提出一个待批准的子节点标题','Propose a child-node title for approval')} className="min-w-0 flex-1 rounded border border-gray-700 bg-gray-900 px-2 py-1.5 text-xs text-gray-100" /><button type="button" disabled={busy || !artifactTitle.trim()} onClick={proposeChild} className="rounded bg-purple-700 px-2 py-1.5 text-xs text-white disabled:opacity-50">{u('新增提案','新增提案','Add proposal')}</button></div>}<div className="mt-3 space-y-2">{artifacts.length === 0 ? <div className="text-xs text-gray-500">{u('尚無產物提案。','暂无产物提案。','No artifact proposals.')}</div> : artifacts.map((artifact) => <div key={artifact.id} className="rounded border border-gray-800 bg-gray-950/50 p-2"><div className="flex justify-between gap-2 text-xs"><span className="text-gray-200">{artifact.artifact_type === "create_child" ? u(`新增子節點：${String(artifact.payload.title || '')}`,`新增子节点：${String(artifact.payload.title || '')}`,`Add child node: ${String(artifact.payload.title || '')}`) : artifact.artifact_type}</span><span className="text-gray-500">{artifact.status}</span></div>{artifact.status === "pending" && <><input value={reviewNotes[artifact.id] || ""} onChange={(event) => setReviewNotes({ ...reviewNotes, [artifact.id]: event.target.value })} placeholder={u("審核備註（可選）", "审核备注（可选）", "Review notes (optional)")} className="mt-2 w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200" /><div className="mt-2 flex gap-2"><button type="button" onClick={() => reviewArtifact(artifact, "approve")} className="rounded border border-emerald-700 px-2 py-1 text-xs text-emerald-300">{u('核准套用','批准并应用','Approve and apply')}</button><button type="button" onClick={() => reviewArtifact(artifact, "reject")} className="rounded border border-red-800 px-2 py-1 text-xs text-red-300">{u('退回','退回','Reject')}</button></div></>}{artifact.review_note && <div className="mt-1 text-[11px] text-gray-500">{u('備註：','备注：','Note: ')}{artifact.review_note}</div>}</div>)}</div></div>}
    </div>
  </div>;
}
