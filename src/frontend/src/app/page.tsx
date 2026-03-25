"use client";

import { useEffect, useState } from "react";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { MindMap } from "@/components/MindMap";
import { NodePanel } from "@/components/NodePanel";
import { useStore } from "@/stores/useStore";

export default function HomePage() {
  const loadProjects = useStore((s) => s.loadProjects);
  const projects = useStore((s) => s.projects);
  const currentProject = useStore((s) => s.currentProject);
  const selectProject = useStore((s) => s.selectProject);
  const createProject = useStore((s) => s.createProject);
  const selectedNode = useStore((s) => s.selectedNode);
  const loading = useStore((s) => s.loading);
  const error = useStore((s) => s.error);
  const errorStatus = useStore((s) => s.errorStatus);
  const errorRetryable = useStore((s) => s.errorRetryable);
  const dismissError = useStore((s) => s.dismissError);

  const [showNewProject, setShowNewProject] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (!error || !errorRetryable) return;

    const timeoutId = window.setTimeout(() => {
      dismissError();
    }, 5000);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [dismissError, error, errorRetryable]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    await createProject(newName.trim(), newDesc.trim() || undefined);
    setNewName("");
    setNewDesc("");
    setShowNewProject(false);
  };

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
          onClick={() => setShowNewProject(!showNewProject)}
          className="rounded-md border border-blue-500/30 bg-[var(--accent-soft)] px-3 py-1.5 text-xs text-blue-300 hover:border-blue-400/50 hover:text-blue-200"
        >
          + 新專案
        </button>

        {currentProject && (
          <div className="ml-auto min-w-0 text-right">
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

      {error && (
        <div className="px-4 pt-4">
          <div
            role="alert"
            className="surface-panel flex items-start gap-3 rounded-2xl px-4 py-3 text-sm text-[var(--text-primary)]"
          >
            <div className="min-w-0 flex-1">
              <div className="eyebrow-label">Request error</div>
              <p className="mt-1 break-words text-[var(--text-primary)]">{error}</p>
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                {errorStatus !== null ? `HTTP ${errorStatus}` : "Request failed"}
                {errorRetryable ? " · 可重試，將於 5 秒後自動關閉" : " · 請手動確認後再繼續"}
              </p>
            </div>
            <button
              type="button"
              onClick={dismissError}
              className="surface-subtle shrink-0 rounded-lg px-3 py-1.5 text-xs text-[var(--text-primary)]"
            >
              關閉
            </button>
          </div>
        </div>
      )}

      {/* Main content */}
      <ErrorBoundary>
        <div className="flex-1 flex overflow-hidden">
          {/* Mind map canvas */}
          <div className="flex-1 relative">
            {loading ? (
              <div className="flex h-full items-center justify-center text-[var(--text-muted)]">
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
      </ErrorBoundary>
    </div>
  );
}
