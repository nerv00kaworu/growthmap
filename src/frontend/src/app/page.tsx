"use client";

import { useEffect, useState, useCallback } from "react";
import { useStore } from "@/stores/useStore";
import { MindMap } from "@/components/MindMap";
import { NodePanel } from "@/components/NodePanel";
import { Toast } from "@/components/Toast";

export default function HomePage() {
  const loadProjects = useStore((s) => s.loadProjects);
  const projects = useStore((s) => s.projects);
  const currentProject = useStore((s) => s.currentProject);
  const selectProject = useStore((s) => s.selectProject);
  const createProject = useStore((s) => s.createProject);
  const selectedNode = useStore((s) => s.selectedNode);
  const loading = useStore((s) => s.loading);
  const error = useStore((s) => s.error);

  const [showNewProject, setShowNewProject] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [showActions, setShowActions] = useState(false);
  const [actions, setActions] = useState<{ id: string; action_type: string; actor_type: string; created_at: string }[]>([]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    await createProject(newName.trim(), newDesc.trim() || undefined);
    setNewName("");
    setNewDesc("");
    setShowNewProject(false);
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

  const handleShowActions = useCallback(async () => {
    if (!currentProject) return;
    try {
      const res = await fetch(`/api/projects/${currentProject.id}/actions?limit=5`);
      if (!res.ok) throw new Error("無法載入動作記錄");
      const data = await res.json();
      setActions(data);
      setShowActions((v) => !v);
    } catch (e: unknown) {
      useStore.setState({ error: (e as Error).message });
    }
  }, [currentProject]);

  return (
    <div className="h-screen flex flex-col">
      {/* Top bar */}
      <header className="h-14 border-b border-[var(--border)] bg-[var(--bg-panel)]/95 backdrop-blur flex items-center px-4 gap-4 shrink-0">
        <div>
          <div className="eyebrow-label">Project growth workspace</div>
          <h1 className="text-sm font-semibold text-[var(--text-primary)] tracking-wide">🌳 GrowthMap</h1>
        </div>
        <div className="h-6 w-px bg-[var(--border)]" />

        {/* Project selector */}
        <select
          value={currentProject?.id || ""}
          aria-label="選擇專案"
          onChange={(e) => {
            const p = projects.find((p) => p.id === e.target.value);
            if (p) selectProject(p);
          }}
          className="surface-subtle rounded px-2.5 py-1.5 text-xs text-[var(--text-primary)]"
        >
          <option value="">選擇專案...</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        <button
          type="button"
          aria-controls="new-project-panel"
          aria-expanded={showNewProject}
          onClick={() => setShowNewProject(!showNewProject)}
          className="rounded-md border border-blue-500/30 bg-[var(--accent-soft)] px-3 py-1.5 text-xs text-blue-300 hover:border-blue-400/50 hover:text-blue-200"
        >
          + 新專案
        </button>

        {currentProject && (
          <>
            <button
              type="button"
              onClick={handleExport}
              className="rounded-md border border-gray-600/50 bg-gray-800/40 px-3 py-1.5 text-xs text-gray-300 hover:text-gray-100"
            >
              📄 匯出
            </button>
            <div className="relative">
              <button
                type="button"
                onClick={handleShowActions}
                className="rounded-md border border-gray-600/50 bg-gray-800/40 px-3 py-1.5 text-xs text-gray-300 hover:text-gray-100"
              >
                ↩ 復原
              </button>
              {showActions && (
                <div className="absolute top-full left-0 mt-1 w-72 bg-[#111] border border-gray-700 rounded-lg shadow-xl z-50 p-2">
                  <div className="text-xs text-gray-500 mb-2 px-1">最近 5 筆操作記錄</div>
                  {actions.length === 0 ? (
                    <div className="text-xs text-gray-500 px-1 py-2">無記錄</div>
                  ) : (
                    <div className="space-y-1">
                      {actions.map((a) => (
                        <div key={a.id} className="px-2 py-1.5 rounded bg-gray-900/60 text-xs">
                          <span className="text-blue-400">{a.action_type}</span>
                          <span className="text-gray-500 ml-2">{a.actor_type}</span>
                          <div className="text-gray-600 text-[10px]">{new Date(a.created_at).toLocaleString("zh-TW")}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="text-[10px] text-gray-600 px-1 mt-2">* 實際復原功能即將推出</div>
                </div>
              )}
            </div>
          </>
        )}

        {currentProject && (
          <div className="ml-auto min-w-0 text-right">
            <div className="eyebrow-label">Current project</div>
            <span className="block truncate text-xs text-[var(--text-muted)]">{currentProject.description || currentProject.name}</span>
          </div>
        )}
      </header>

      {/* New project modal */}
      {showNewProject && (
        <div id="new-project-panel" className="surface-panel border-x-0 border-t-0 rounded-none p-4 flex gap-3 items-end">
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
        {/* Mind map canvas */}
        <div className="flex-1 relative">
          {loading ? (
            <div className="flex items-center justify-center h-full text-gray-500">
              載入中...
            </div>
          ) : (
            <MindMap />
          )}
        </div>

        {/* Right panel */}
        <div
          className="border-l border-[var(--border)] bg-[var(--bg-panel)] transition-all duration-300 overflow-hidden surface-panel rounded-none border-y-0 border-r-0"
          style={{ width: selectedNode ? 340 : 0 }}
        >
          <NodePanel />
        </div>
      </div>

      {/* Error Toast */}
      {error && (
        <Toast message={error} onDismiss={() => useStore.setState({ error: null })} />
      )}
    </div>
  );
}
