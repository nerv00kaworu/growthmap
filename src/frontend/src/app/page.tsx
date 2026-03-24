"use client";

import { useEffect, useState } from "react";
import { useStore } from "@/stores/useStore";
import { MindMap } from "@/components/MindMap";
import { NodePanel } from "@/components/NodePanel";

export default function HomePage() {
  const loadProjects = useStore((s) => s.loadProjects);
  const projects = useStore((s) => s.projects);
  const currentProject = useStore((s) => s.currentProject);
  const selectProject = useStore((s) => s.selectProject);
  const createProject = useStore((s) => s.createProject);
  const selectedNode = useStore((s) => s.selectedNode);
  const loading = useStore((s) => s.loading);

  const [showNewProject, setShowNewProject] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

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

  return (
    <div className="h-screen flex flex-col">
      {/* Top bar */}
      <header className="h-12 bg-[#0d0d0d] border-b border-gray-800 flex items-center px-4 gap-4 shrink-0">
        <h1 className="text-sm font-bold text-gray-300 tracking-wider">🌳 GrowthMap</h1>
        <div className="h-4 w-px bg-gray-700" />

        {/* Project selector */}
        <select
          value={currentProject?.id || ""}
          onChange={(e) => {
            const p = projects.find((p) => p.id === e.target.value);
            if (p) selectProject(p);
          }}
          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300"
        >
          <option value="">選擇專案...</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        <button
          onClick={() => setShowNewProject(!showNewProject)}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          + 新專案
        </button>

        {currentProject && (
          <span className="ml-auto text-xs text-gray-500">
            {currentProject.description}
          </span>
        )}
      </header>

      {/* New project modal */}
      {showNewProject && (
        <div className="bg-gray-900 border-b border-gray-700 p-4 flex gap-3 items-end">
          <div className="flex-1">
            <label className="text-xs text-gray-500">專案名稱</label>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 mt-1"
              placeholder="例：Fate Origin Agent"
              autoFocus
            />
          </div>
          <div className="flex-1">
            <label className="text-xs text-gray-500">描述（選填）</label>
            <input
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 mt-1"
              placeholder="一句話描述"
            />
          </div>
          <button onClick={handleCreate} className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded">
            建立
          </button>
          <button onClick={() => setShowNewProject(false)} className="px-3 py-1.5 text-gray-500 hover:text-gray-300 text-sm">
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
          className="border-l border-gray-800 bg-[#111] transition-all duration-300 overflow-hidden"
          style={{ width: selectedNode ? 340 : 0 }}
        >
          <NodePanel />
        </div>
      </div>
    </div>
  );
}
