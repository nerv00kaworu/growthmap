"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useStore } from "@/stores/useStore";
import { MindMap } from "@/components/MindMap";
import { NodePanel } from "@/components/NodePanel";
import { Toast } from "@/components/Toast";
import { Settings } from "@/components/Settings";
import { AgentSessions } from "@/components/AgentSessions";
import { AgentPortPanel } from "@/components/AgentPortPanel";
import { api } from "@/lib/api";
import { useEntitlement } from "@/lib/entitlement";
import { useAgentPortDesktopControl } from "@/lib/agent-port-control";

export default function HomePage() {
  const agentPortDesktopControl = useAgentPortDesktopControl();
  const loadProjects = useStore((s) => s.loadProjects);
  const projects = useStore((s) => s.projects);
  const currentProject = useStore((s) => s.currentProject);
  const selectProject = useStore((s) => s.selectProject);
  const createProject = useStore((s) => s.createProject);
  const selectedNode = useStore((s) => s.selectedNode);
  const selectedNodeId = useStore((s) => s.selectedNodeId);
  const loading = useStore((s) => s.loading);
  const error = useStore((s) => s.error);
  const undoStack = useStore((s) => s.undoStack);
  const undo = useStore((s) => s.undo);
  const toast = useStore((s) => s.toast);
  const setToast = useStore((s) => s.setToast);
  const searchQuery = useStore((s) => s.searchQuery);
  const setSearchQuery = useStore((s) => s.setSearchQuery);
  const highlightedNodeIds = useStore((s) => s.highlightedNodeIds);
  const selectNode = useStore((s) => s.selectNode);
  const expandNode = useStore((s) => s.expandNode);
  const deepenNode = useStore((s) => s.deepenNode);
  const deleteNode = useStore((s) => s.deleteNode);

  const branches = useStore((s) => s.branches);
  const currentBranch = useStore((s) => s.currentBranch);
  const selectBranch = useStore((s) => s.selectBranch);
  const archiveBranch = useStore((s) => s.archiveBranch);

  const [showNewProject, setShowNewProject] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [showAgentSessions, setShowAgentSessions] = useState(false);
  const [showAgentPort, setShowAgentPort] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const [appInfo, setAppInfo] = useState<Awaited<ReturnType<NonNullable<typeof window.growthmapDesktop>["appInfo"]["get"]>> | null>(null);
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [showBranchHistory, setShowBranchHistory] = useState(false);
  const [branchHistory, setBranchHistory] = useState<{ id: string; action_type: string; created_at: string }[]>([]);
  const [branchHistoryLoading, setBranchHistoryLoading] = useState(false);
  const { entitlement, refreshEntitlement } = useEntitlement();
  // Keep mutation controls fail-closed until the backend has answered authoritatively.
  const readOnly = entitlement?.mutations_allowed !== true;
  const importRef = useRef<HTMLInputElement>(null);
  const moreMenuRef = useRef<HTMLDivElement>(null);

  // Build id->title map for search display
  const rootNode = useStore((s) => s.rootNode);
  const nodeMap = useCallback(() => {
    const map: Record<string, string> = {};
    function walk(node: import("@/lib/types").GNode) {
      map[node.id] = node.title;
      for (const c of node.children || []) walk(c);
    }
    if (rootNode) walk(rootNode);
    return map;
  }, [rootNode]);

  const idTitleMap = nodeMap();

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (!currentProject && projects.length > 0) {
      selectProject(projects[0]);
    }
  }, [currentProject, projects, selectProject]);

  // Auto-dismiss toast
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 5000);
      return () => clearTimeout(t);
    }
  }, [toast, setToast]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowMoreMenu(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    await createProject(newName.trim(), newDesc.trim() || undefined);
    setNewName("");
    setNewDesc("");
    setShowNewProject(false);
  };

  const handleExportSpec = async () => {
    if (!currentProject) return;
    try {
      const md = await api.exportSpec(currentProject.id);
      const blob = new Blob([md], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${currentProject.name}_spec.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      useStore.setState({ error: (e as Error).message });
    }
  };

  const handleExport = async () => {
    if (!currentProject) return;
    try {
      const res = await fetch(`/api/projects/${currentProject.id}/export`);
      if (!res.ok) throw new Error("匯出失敗");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${currentProject.name}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      useStore.setState({ error: (e as Error).message });
    }
  };

  const handleExportJSON = async () => {
    if (!currentProject) return;
    try {
      const res = await fetch(`/api/projects/${currentProject.id}/export-json`);
      if (!res.ok) throw new Error("JSON 匯出失敗");
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${currentProject.name}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      useStore.setState({ error: (e as Error).message });
    }
  };

  const handleProjectStatus = async (status: "active" | "archived") => {
    if (!currentProject) return;
    try {
      await api.updateProject(currentProject.id, { status });
      await loadProjects();
      setToast(status === "active" ? "✅ 專案已恢復" : "✅ 專案已封存；資料仍可讀與匯出");
    } catch (e: unknown) { useStore.setState({ error: (e as Error).message }); }
  };

  const importLicense = async () => {
    const desktop = (window as typeof window & { growthmapDesktop?: { license: { import(): Promise<unknown> } } }).growthmapDesktop;
    if (!desktop) { setToast("License 匯入僅在桌面版提供"); return; }
    try {
      const imported = await desktop.license.import();
      if (imported === null) return;
      await refreshEntitlement();
      setToast("✅ License 已驗證並匯入");
    } catch (e: unknown) { useStore.setState({ error: (e as Error).message }); }
  };

  const [manualPayment, setManualPayment] = useState<Awaited<ReturnType<NonNullable<typeof window.growthmapDesktop>["purchase"]["info"]>> | null>(null);
  const loadManualPayment = useCallback(async () => {
    if (!window.growthmapDesktop) return;
    try { setManualPayment(await window.growthmapDesktop.purchase.info()); }
    catch (e: unknown) { useStore.setState({ error: (e as Error).message }); }
  }, []);
  useEffect(() => { if (window.growthmapDesktop && entitlement?.state !== "paid") loadManualPayment(); }, [entitlement?.state, loadManualPayment]);
  const openPurchase = async (rail: "paypal" | "email" | "x") => {
    if (!window.growthmapDesktop) { setToast("購買僅在桌面版提供"); return; }
    try { await window.growthmapDesktop.purchase.open(rail); }
    catch (e: unknown) { useStore.setState({ error: (e as Error).message }); }
  };
  const copyBaseAddress = async () => {
    if (!window.growthmapDesktop) return;
    try { await window.growthmapDesktop.purchase.copyBaseAddress(); setToast("✅ Base USDC 收款地址已複製"); }
    catch (e: unknown) { useStore.setState({ error: (e as Error).message }); }
  };

  const checkUpdates = async () => {
    if (!window.growthmapDesktop) return;
    try { await window.growthmapDesktop.updates.check(); }
    catch (e: unknown) { useStore.setState({ error: (e as Error).message }); }
  };
  const openAbout = async () => {
    if (!window.growthmapDesktop) return;
    try { setAppInfo(await window.growthmapDesktop.appInfo.get()); setShowAbout(true); setShowMoreMenu(false); }
    catch (e: unknown) { useStore.setState({ error: (e as Error).message }); }
  };

  const handleArchiveBranch = async () => {
    if (!currentBranch) return;
    if (!confirm(`確定封存方案線「${currentBranch.name}」？\n\n封存後不會刪除資料，可在方案線管理中查看歷史紀錄。`)) return;
    await archiveBranch(currentBranch.id);
  };

  const openBranchHistory = async () => {
    if (!currentProject) return;
    setBranchHistoryLoading(true);
    setShowBranchHistory(true);
    try {
      const allBranches = await api.listBranches(currentProject.id, true);
      const rows = await Promise.all(allBranches.map(async (branch) => {
        const history = await api.getBranchHistory(branch.id);
        return history.map((entry) => ({ id: entry.id, action_type: `${branch.name} · ${entry.action_type}`, created_at: entry.created_at }));
      }));
      setBranchHistory(rows.flat().sort((a, b) => b.created_at.localeCompare(a.created_at)));
    } catch (e: unknown) {
      useStore.setState({ error: (e as Error).message });
      setShowBranchHistory(false);
    } finally {
      setBranchHistoryLoading(false);
    }
  };

  const handleImportJSON = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const res = await fetch("/api/projects/import-json", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("匯入失敗");
      await loadProjects();
      setToast("✅ 匯入成功！");
    } catch (e: unknown) {
      useStore.setState({ error: (e as Error).message });
    }
    if (importRef.current) importRef.current.value = "";
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
      const isInput = tag === "input" || tag === "textarea" || tag === "select";

      if (e.key === "Escape") {
        selectNode(null);
        setShowShortcuts(false);
      }

      if (!isInput) {
        if ((e.key === "Delete" || e.key === "Backspace") && selectedNodeId) {
          if (confirm("確定刪除此節點？")) {
            deleteNode(selectedNodeId);
          }
        }
        if (e.key === "e" || e.key === "E") {
          if (selectedNodeId) expandNode(selectedNodeId);
        }
        if (e.key === "d" || e.key === "D") {
          if (selectedNodeId) deepenNode(selectedNodeId);
        }
        if ((e.ctrlKey || e.metaKey) && e.key === "z") {
          e.preventDefault();
          undo();
        }
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [selectedNodeId, selectNode, deleteNode, expandNode, deepenNode, undo]);

  const topBtnClass = "rounded-md border border-gray-600/50 bg-gray-800/40 px-3 py-1.5 text-xs text-gray-300 hover:text-gray-100 shrink-0";

  return (
    <div className="h-screen flex flex-col">
      {/* Top bar */}
      <header className="h-14 border-b border-[var(--border)] bg-[var(--bg-panel)]/95 backdrop-blur flex items-center px-3 gap-2 shrink-0 flex-nowrap overflow-x-auto overflow-y-visible relative z-40">
        <div className="shrink-0 flex items-center h-full">
          <h1 data-testid="growthmap-title" className="text-sm font-semibold text-[var(--text-primary)] tracking-wide">🌳 GrowthMap</h1>
        </div>
        <div className="h-6 w-px bg-[var(--border)] shrink-0" />

        {/* Project selector */}
        <select
          value={currentProject?.id || ""}
          aria-label="選擇專案"
          onChange={(e) => {
            const p = projects.find((p) => p.id === e.target.value);
            if (p) selectProject(p);
          }}
          className="surface-subtle rounded-md px-2.5 py-1.5 text-xs text-[var(--text-primary)] shrink-0 border border-gray-700/60 hover:border-gray-500/70 max-w-36"
        >
          <option value="">選擇專案...</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.status === "archived" ? "🗄 " : ""}{p.name}</option>
          ))}
        </select>

        {/* Branch selector */}
        {currentProject && (
          <>
            <select
              value={currentBranch?.id || "main"}
              aria-label="選擇分支"
              onChange={(e) => {
                if (e.target.value === "main") {
                  selectBranch(null);
                } else {
                  const b = branches.find((b) => b.id === e.target.value);
                  if (b) selectBranch(b);
                }
              }}
              className="surface-subtle rounded-md px-2.5 py-1.5 text-xs shrink-0 text-purple-300 border border-purple-700/40 hover:border-purple-500/60 max-w-40"
            >
              <option value="main">🌿 主線（main）</option>
              {branches.map((b) => (
                <option key={b.id} value={b.id}>🔀 方案線：{b.name}</option>
              ))}
            </select>
          </>
        )}

        <span data-testid="entitlement-status" className="shrink-0 text-[10px] text-gray-400">
          {entitlement === null ? "Checking entitlement…" : entitlement.state === "paid" ? `Paid · perpetual v${entitlement.major_version} · unlimited` : entitlement.state === "trial" ? `Trial · ${entitlement.trial_days_remaining} day(s) · ${projects.filter(p => p.status === "active").length}/2` : "Read-only extraction · exports available"}
        </span>
        <button
          data-testid="new-project-button"
          type="button"
          onClick={() => setShowNewProject(!showNewProject)}
          disabled={readOnly}
          className="rounded-md border border-blue-500/30 bg-[var(--accent-soft)] px-3 py-1.5 text-xs text-blue-300 hover:border-blue-400/50 hover:text-blue-200 shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          + 新專案
        </button>

        {currentProject && (
          <div ref={moreMenuRef} className="shrink-0">
            <button
              type="button"
              onClick={() => setShowMoreMenu((v) => !v)}
              className={topBtnClass}
              title="更多操作"
            >
              ⋯ 更多
            </button>
          </div>
        )}

        {/* Search */}
        <div className="relative shrink-0 hidden md:block">
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && highlightedNodeIds.length > 0) {
                selectNode(highlightedNodeIds[0]);
              }
              if (e.key === "Escape") setSearchQuery("");
            }}
            placeholder="🔍 搜尋節點..."
            className="surface-subtle rounded px-3 py-1.5 text-xs text-[var(--text-primary)] w-36 focus:w-48 transition-all duration-200 focus:border-blue-500/50 focus:outline-none"
          />
          {searchQuery && highlightedNodeIds.length > 0 && (
            <div className="absolute top-full left-0 mt-1 w-64 bg-[#111] border border-gray-700 rounded-lg shadow-xl z-50 max-h-48 overflow-y-auto">
              <div className="text-[10px] text-gray-500 px-3 py-1">{highlightedNodeIds.length} 個結果</div>
              {highlightedNodeIds.slice(0, 10).map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => { selectNode(id); setSearchQuery(""); }}
                  className="block w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-800"
                >
                  {idTitleMap[id] || id}
                </button>
              ))}
            </div>
          )}
        </div>

        {typeof window !== "undefined" && window.growthmapDesktop && <button data-testid="top-about-growthmap-button" type="button" onClick={openAbout} className="rounded-md border border-cyan-800/50 bg-cyan-950/30 px-2.5 py-1.5 text-xs text-cyan-200 hover:text-cyan-100 shrink-0" title="關於 GrowthMap">ℹ️</button>}
        <button data-testid="desktop-settings-button" type="button" onClick={() => setShowSettings(true)} className="rounded-md border border-gray-600/50 bg-gray-800/40 px-2.5 py-1.5 text-xs text-gray-300 hover:text-gray-100 shrink-0" title="設定">⚙️</button>
        <button
          type="button"
          onClick={() => setShowShortcuts(true)}
          title="鍵盤快捷鍵"
          className={`${topBtnClass} px-2.5 hidden md:inline-block`}
        >
          ⌨️
        </button>

      </header>

      {showMoreMenu && currentProject && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowMoreMenu(false)}>
          <div className="w-full max-w-md rounded-xl border border-gray-700 bg-gray-900 p-5 shadow-2xl space-y-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-gray-100">⋯ 更多操作</h2>
                <p className="mt-1 text-xs text-gray-500">
                  {currentBranch ? `目前方案線：${currentBranch.name}` : "匯入匯出、復原與方案線管理"}
                </p>
              </div>
              <button type="button" onClick={() => setShowMoreMenu(false)} className="text-gray-500 hover:text-gray-300 text-lg">×</button>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={() => { handleExportSpec(); setShowMoreMenu(false); }} className="rounded-lg border border-green-800/40 bg-green-950/20 px-3 py-2.5 text-left text-xs text-green-300 hover:bg-green-900/30">📋 匯出規格</button>
              <button type="button" onClick={() => { handleExport(); setShowMoreMenu(false); }} className="rounded-lg border border-gray-700 bg-gray-800/50 px-3 py-2.5 text-left text-xs text-gray-300 hover:bg-gray-800">📄 匯出 Markdown</button>
              <button type="button" onClick={() => { handleExportJSON(); setShowMoreMenu(false); }} className="rounded-lg border border-gray-700 bg-gray-800/50 px-3 py-2.5 text-left text-xs text-gray-300 hover:bg-gray-800">📤 匯出 JSON</button>
              <label className={`rounded-lg border border-gray-700 bg-gray-800/50 px-3 py-2.5 text-left text-xs text-gray-300 ${readOnly ? "opacity-40 pointer-events-none" : "hover:bg-gray-800 cursor-pointer"}`}>
                📥 匯入 JSON
                <input
                  ref={importRef}
                  type="file"
                  accept=".json"
                  onChange={(e) => { handleImportJSON(e); setShowMoreMenu(false); }}
                  className="hidden"
                />
              </label>
              <button
                type="button"
                onClick={() => { undo(); setShowMoreMenu(false); }}
                disabled={undoStack.length === 0}
                className="rounded-lg border border-gray-700 bg-gray-800/50 px-3 py-2.5 text-left text-xs text-gray-300 hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ↩ 復原 {undoStack.length > 0 && <span className="ml-1 text-gray-500">({undoStack.length})</span>}
              </button>
              <button type="button" onClick={() => { setShowSettings(true); setShowMoreMenu(false); }} disabled={readOnly} className="rounded-lg border border-gray-700 bg-gray-800/50 px-3 py-2.5 text-left text-xs text-gray-300 hover:bg-gray-800 disabled:opacity-40">⚙️ LLM 設定</button>
              <button type="button" onClick={() => { importLicense(); setShowMoreMenu(false); }} className="rounded-lg border border-amber-800/40 bg-amber-950/20 px-3 py-2.5 text-left text-xs text-amber-200">🔑 匯入 License</button>
              {entitlement?.state !== "paid" && <section data-testid="purchase-panel" className="space-y-2 rounded-lg border border-amber-700/50 bg-amber-900/20 p-3 text-xs text-amber-100"><strong>購買 v1 永久授權</strong><p className="text-[10px] text-amber-200/70">首 50 筆確認付款 10 USDC／USD；其後 29。永久、同主版本更新、2 部個人裝置、無專案上限。</p>{manualPayment && <><div className="rounded border border-amber-800/50 p-2"><div className="font-medium">Base 原生 USDC</div><code data-testid="base-payment-address" className="break-all text-[10px]">{manualPayment.basePayee}</code><button type="button" onClick={copyBaseAddress} className="mt-1 rounded border border-amber-600 px-2 py-1">複製收款地址</button><p className="mt-1 text-[10px] text-red-300">只接受 Base（eip155:8453）上的 Circle USDC；請勿轉 ETH 或其他鏈／代幣。</p></div><button type="button" onClick={() => openPurchase("paypal")} className="mr-2 rounded border border-amber-600 px-2 py-1">開啟 PayPal</button><button type="button" onClick={() => openPurchase("email")} className="mr-2 rounded border border-amber-600 px-2 py-1">Email 回報付款</button><button type="button" onClick={() => openPurchase("x")} className="rounded border border-amber-600 px-2 py-1">X 聯絡</button><p className="text-[10px] text-gray-400">付款後請提供付款方式、PayPal transaction ID 或 Base tx hash、License 名稱及聯絡 Email。交易須人工核對；截圖不構成付款證明。收到簽章 JSON 後請使用「匯入 License」。</p></>}</section>}
              {typeof window !== "undefined" && window.growthmapDesktop && <button data-testid="check-updates-button" type="button" onClick={() => { checkUpdates(); setShowMoreMenu(false); }} className="rounded-lg border border-blue-800/40 bg-blue-950/20 px-3 py-2.5 text-left text-xs text-blue-200">⬆️ 前往下載新版</button>}
              {typeof window !== "undefined" && window.growthmapDesktop && <button data-testid="about-growthmap-button" type="button" onClick={openAbout} className="rounded-lg border border-cyan-800/40 bg-cyan-950/20 px-3 py-2.5 text-left text-xs text-cyan-200">ℹ️ 關於 GrowthMap</button>}
              <button type="button" disabled={readOnly} onClick={() => { handleProjectStatus(currentProject.status === "active" ? "archived" : "active"); setShowMoreMenu(false); }} className="rounded-lg border border-gray-700 bg-gray-800/50 px-3 py-2.5 text-left text-xs text-gray-300 disabled:opacity-40">{currentProject.status === "active" ? "🗄️ 封存專案" : "♻️ 恢復專案"}</button>
              <button type="button" onClick={() => { setShowAgentSessions(true); setShowMoreMenu(false); }} disabled={!rootNode} className="rounded-lg border border-blue-800/40 bg-blue-950/20 px-3 py-2.5 text-left text-xs text-blue-200 hover:bg-blue-900/30 disabled:opacity-40">🤖 Agent 工作階段</button>
              {agentPortDesktopControl && <button data-testid="agent-port-menu-entry" type="button" onClick={() => { setShowAgentPort(true); setShowMoreMenu(false); }} disabled={!rootNode} className="rounded-lg border border-purple-800/40 bg-purple-950/20 px-3 py-2.5 text-left text-xs text-purple-200 hover:bg-purple-900/30 disabled:opacity-40">🔌 Agent Port</button>}
              <button type="button" onClick={() => { setShowShortcuts(true); setShowMoreMenu(false); }} className="rounded-lg border border-gray-700 bg-gray-800/50 px-3 py-2.5 text-left text-xs text-gray-300 hover:bg-gray-800">⌨️ 快捷鍵</button>
              <button type="button" onClick={() => { openBranchHistory(); setShowMoreMenu(false); }} className="rounded-lg border border-purple-800/40 bg-purple-950/20 px-3 py-2.5 text-left text-xs text-purple-200 hover:bg-purple-900/30">🗂️ 方案線歷史</button>
            </div>

            <div className="rounded-lg border border-red-900/30 bg-red-950/10 p-3 space-y-2">
              <div className="text-[10px] uppercase tracking-[0.18em] text-red-400/70">危險操作</div>
              <button
                type="button"
                onClick={() => { handleArchiveBranch(); setShowMoreMenu(false); }}
                disabled={!currentBranch}
                className="w-full rounded-lg border border-red-900/40 bg-red-950/20 px-3 py-2.5 text-left text-xs text-red-300 hover:bg-red-900/30 disabled:opacity-40 disabled:cursor-not-allowed"
                title={currentBranch ? `封存方案線：${currentBranch.name}` : "目前是主線，請先切到方案線後才能封存"}
              >
                🗃️ {currentBranch ? `封存方案線：${currentBranch.name}` : "主線不可封存"}
              </button>
            </div>
          </div>
        </div>
      )}

      {showAbout && appInfo && (
        <div className="fixed inset-0 z-[140] flex items-center justify-center bg-black/70 px-4" onClick={() => setShowAbout(false)}>
          <div data-testid="about-growthmap-dialog" className="w-full max-w-lg rounded-xl border border-cyan-800/50 bg-gray-950 p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between"><div><h2 className="text-lg font-semibold text-gray-100">{appInfo.productName}</h2><p className="mt-1 text-xs text-gray-500">版本 {appInfo.version}</p></div><button type="button" onClick={() => setShowAbout(false)} className="text-xl text-gray-500 hover:text-gray-300">×</button></div>
            <div className="mt-5 space-y-3 text-sm text-gray-300"><p><strong>製作者：</strong>{appInfo.creator}</p><p>{appInfo.copyright}</p><p className="rounded border border-amber-800/50 bg-amber-950/20 p-3 text-xs text-amber-200">此版本依製作者選擇未使用 Authenticode簽章；Windows可能顯示「未知發行者」或 SmartScreen提示。請只從官方 Releases下載並核對 SHA-256。</p><p className="text-xs text-gray-400">更新模式：人工下載。GrowthMap不會在背景靜默下載或安裝更新。</p></div>
            <div className="mt-5 flex flex-wrap gap-2"><button type="button" onClick={() => window.growthmapDesktop?.appInfo.open("releases")} className="rounded border border-blue-700 px-3 py-2 text-xs text-blue-200">官方 Releases</button><button type="button" onClick={() => window.growthmapDesktop?.appInfo.open("email")} className="rounded border border-gray-700 px-3 py-2 text-xs text-gray-200">Email</button><button type="button" onClick={() => window.growthmapDesktop?.appInfo.open("x")} className="rounded border border-gray-700 px-3 py-2 text-xs text-gray-200">X</button></div>
          </div>
        </div>
      )}

      {showBranchHistory && (
        <div className="fixed inset-0 z-[130] flex items-center justify-center bg-black/60 px-4" onClick={() => setShowBranchHistory(false)}>
          <div className="w-full max-w-lg rounded-xl border border-gray-700 bg-gray-900 p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-gray-100">🗂️ 方案線歷史</h2>
                <p className="mt-1 text-xs text-gray-500">包含建立、合併與封存紀錄；封存資料仍可追溯。</p>
              </div>
              <button type="button" onClick={() => setShowBranchHistory(false)} className="text-lg text-gray-500 hover:text-gray-300">×</button>
            </div>
            <div className="mt-4 max-h-72 space-y-2 overflow-y-auto">
              {branchHistoryLoading ? <div className="py-6 text-center text-sm text-gray-500">讀取方案線歷史中…</div> : branchHistory.length === 0 ? <div className="py-6 text-center text-sm text-gray-500">此專案尚無方案線歷史。</div> : branchHistory.map((entry) => (
                <div key={entry.id} className="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-2">
                  <div className="text-sm text-gray-200">{entry.action_type.replaceAll("_", " ")}</div>
                  <div className="mt-0.5 text-[11px] text-gray-500">{new Date(entry.created_at).toLocaleString()}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* New project modal */}
      {showNewProject && (
        <div className="surface-panel border-x-0 border-t-0 rounded-none p-4 flex gap-3 items-end">
          <div className="flex-1">
            <div className="eyebrow-label">專案名稱</div>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              className="mt-1 w-full rounded px-3 py-2 text-sm text-[var(--text-primary)] surface-subtle"
              placeholder="例：Fate Origin Agent"
            />
          </div>
          <div className="flex-1">
            <div className="eyebrow-label">描述（選填）</div>
            <input
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              className="mt-1 w-full rounded px-3 py-2 text-sm text-[var(--text-primary)] surface-subtle"
              placeholder="一句話描述"
            />
          </div>
          <button type="button" onClick={handleCreate} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg">
            建立
          </button>
          <button type="button" onClick={() => setShowNewProject(false)} className="px-3 py-2 text-[var(--text-faint)] hover:text-[var(--text-primary)] text-sm">
            取消
          </button>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 relative">
          {loading ? (
            <div className="flex items-center justify-center h-full text-gray-500">
              <div className="text-center animate-pulse space-y-1">
                <div className="text-sm text-gray-400">正在切換{currentBranch ? "分支" : "專案"}…</div>
                <div className="text-xs text-gray-600">同步樹狀資料中</div>
              </div>
            </div>
          ) : (
            <MindMap />
          )}
        </div>

        <div
          className="border-l border-[var(--border)] bg-[var(--bg-panel)] transition-all duration-300 overflow-hidden surface-panel rounded-none border-y-0 border-r-0"
          style={{ width: selectedNode ? "50vw" : 0 }}
        >
          <NodePanel />
        </div>
      </div>

      {/* Settings Modal */}
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
      {showAgentSessions && currentProject && rootNode && <AgentSessions projectId={currentProject.id} rootNode={rootNode} branches={branches} onClose={() => setShowAgentSessions(false)} />}
      {showAgentPort && currentProject && rootNode && <AgentPortPanel projectId={currentProject.id} rootNode={rootNode} onSelectNode={selectNode} onClose={() => setShowAgentPort(false)} />}

      {/* Keyboard Shortcuts Modal */}
      {showShortcuts && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center"
          onClick={() => setShowShortcuts(false)}
        >
          <div
            className="bg-[#111] border border-gray-700 rounded-xl p-6 shadow-2xl w-80"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-200">⌨️ 鍵盤快捷鍵</h2>
              <button onClick={() => setShowShortcuts(false)} className="text-gray-500 hover:text-gray-300 text-sm">✕</button>
            </div>
            <div className="space-y-2 text-xs">
              {[
                ["Esc", "取消選取 / 關閉面板"],
                ["Delete / Backspace", "刪除選取節點"],
                ["E", "展開選取節點（AI）"],
                ["D", "深化選取節點（AI）"],
                ["Ctrl+Z", "復原"],
              ].map(([key, desc]) => (
                <div key={key} className="flex justify-between items-center">
                  <kbd className="px-2 py-1 bg-gray-800 border border-gray-600 rounded text-gray-300 font-mono">{key}</kbd>
                  <span className="text-gray-400">{desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 max-w-sm">
          <div className="bg-gray-800/90 border border-gray-600 rounded-lg px-4 py-3 shadow-xl flex items-center gap-3">
            <span className="text-gray-200 text-sm flex-1">{toast}</span>
            <button onClick={() => setToast(null)} className="text-gray-500 hover:text-gray-300 text-sm shrink-0">✕</button>
          </div>
        </div>
      )}

      {/* Error Toast */}
      {error && (
        <Toast message={error} onDismiss={() => useStore.setState({ error: null })} />
      )}
    </div>
  );
}
