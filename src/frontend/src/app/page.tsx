"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useStore } from "@/stores/useStore";
import { MindMap } from "@/components/MindMap";
import { NodePanel } from "@/components/NodePanel";
import { Toast } from "@/components/Toast";
import { Settings } from "@/components/Settings";
import { api } from "@/lib/api";

export default function HomePage() {
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

  const [showNewProject, setShowNewProject] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const importRef = useRef<HTMLInputElement>(null);

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

  // Auto-dismiss toast
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 5000);
      return () => clearTimeout(t);
    }
  }, [toast, setToast]);

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

  return (
    <div className="h-screen flex flex-col">
      {/* Top bar */}
      <header className="h-14 border-b border-[var(--border)] bg-[var(--bg-panel)]/95 backdrop-blur flex items-center px-4 gap-3 shrink-0 flex-wrap">
        <div className="shrink-0">
          <div className="eyebrow-label">Project growth workspace</div>
          <h1 className="text-sm font-semibold text-[var(--text-primary)] tracking-wide">🌳 GrowthMap</h1>
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
          className="surface-subtle rounded px-2.5 py-1.5 text-xs text-[var(--text-primary)] shrink-0"
        >
          <option value="">選擇專案...</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        {/* Branch selector */}
        {currentProject && (
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
            className="surface-subtle rounded px-2.5 py-1.5 text-xs shrink-0 text-purple-300 border-purple-700/30"
          >
            <option value="main">🌿 main</option>
            {branches.map((b) => (
              <option key={b.id} value={b.id}>🔀 {b.name}</option>
            ))}
          </select>
        )}

        <button
          type="button"
          onClick={() => setShowNewProject(!showNewProject)}
          className="rounded-md border border-blue-500/30 bg-[var(--accent-soft)] px-3 py-1.5 text-xs text-blue-300 hover:border-blue-400/50 hover:text-blue-200 shrink-0"
        >
          + 新專案
        </button>

        <button
          type="button"
          onClick={() => setShowSettings(true)}
          className="rounded-md border border-gray-600/50 bg-gray-800/40 px-3 py-1.5 text-xs text-gray-300 hover:text-gray-100 shrink-0"
        >
          ⚙️ LLM 設定
        </button>

        {currentProject && (
          <>
            <button
              type="button"
              onClick={handleExportSpec}
              className="rounded-md border border-green-600/40 bg-green-950/30 px-3 py-1.5 text-xs text-green-300 hover:text-green-200 shrink-0"
            >
              📋 匯出規格
            </button>
            <button
              type="button"
              onClick={handleExport}
              className="rounded-md border border-gray-600/50 bg-gray-800/40 px-3 py-1.5 text-xs text-gray-300 hover:text-gray-100 shrink-0"
            >
              📄 匯出
            </button>
            <button
              type="button"
              onClick={handleExportJSON}
              className="rounded-md border border-gray-600/50 bg-gray-800/40 px-3 py-1.5 text-xs text-gray-300 hover:text-gray-100 shrink-0"
            >
              📤 匯出 JSON
            </button>
            <label className="rounded-md border border-gray-600/50 bg-gray-800/40 px-3 py-1.5 text-xs text-gray-300 hover:text-gray-100 shrink-0 cursor-pointer">
              📥 匯入
              <input
                ref={importRef}
                type="file"
                accept=".json"
                onChange={handleImportJSON}
                className="hidden"
              />
            </label>
            <button
              type="button"
              onClick={undo}
              disabled={undoStack.length === 0}
              title={undoStack.length > 0 ? `復原: ${undoStack[0]?.description}` : "無可復原操作"}
              className="rounded-md border border-gray-600/50 bg-gray-800/40 px-3 py-1.5 text-xs text-gray-300 hover:text-gray-100 shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ↩ 復原 {undoStack.length > 0 && <span className="ml-1 text-gray-500">({undoStack.length})</span>}
            </button>
          </>
        )}

        {/* Search */}
        <div className="relative shrink-0">
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

        <button
          type="button"
          onClick={() => setShowShortcuts(true)}
          title="鍵盤快捷鍵"
          className="rounded-md border border-gray-600/50 bg-gray-800/40 px-2.5 py-1.5 text-xs text-gray-300 hover:text-gray-100 shrink-0"
        >
          ⌨️
        </button>

        {currentProject && (
          <div className="ml-auto min-w-0 text-right shrink-0">
            <div className="eyebrow-label">Current project</div>
            <span className="block truncate text-xs text-[var(--text-muted)]">{currentProject.description || currentProject.name}</span>
          </div>
        )}
      </header>

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
              <div className="animate-pulse">載入中...</div>
            </div>
          ) : (
            <MindMap />
          )}
        </div>

        <div
          className="border-l border-[var(--border)] bg-[var(--bg-panel)] transition-all duration-300 overflow-hidden surface-panel rounded-none border-y-0 border-r-0"
          style={{ width: selectedNode ? 420 : 0 }}
        >
          <NodePanel />
        </div>
      </div>

      {/* Settings Modal */}
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}

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
