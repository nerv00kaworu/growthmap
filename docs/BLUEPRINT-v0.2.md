# GrowthMap Blueprint v0.2

> Status note: this file is a **product blueprint**, not a statement of what the current MVP already ships.
> The current implementation is still centered on a SQLite-backed tree editor with AI expand/deepen helpers.

## 定位
一個 GUI 可控、AI 可接手、provider 可插拔的專案生長平台。

## 核心理念
- 節點不是標籤，是可內化單元
- 外向生長（分支）+ 內向生長（內容）
- LLM 負責生成，人類負責裁決
- AI is Worker, not Owner
- Single Source of Truth = Node Graph

## 成功標準
1. 人類能在 GUI 上自然控制專案樹
2. AI 能接手局部分支共同開發
3. 更換 provider 不影響專案本體

## 技術選型
- Frontend: Next.js + React Flow + Zustand
- Backend: FastAPI (Python)
- DB: SQLite + JSON (aiosqlite)
- Provider: 可插拔認知層（藍圖中定義，**目前 MVP 僅支援 env-based OpenAI-compatible 單一 provider**）

## 開發順序
- Phase 1: 核心骨架 (Project/Node/Edge + GUI + CRUD)
- Phase 2: AI 生長 (Suggestion + expand/deepen + provider)
- Phase 3: 共構能力 (agent handoff + session + history)
- Phase 4: 智能路由 (cost routing + fallback)

## 與目前 MVP 的落差

- 已實作：Project / Node / `child_of` Edge / GUI / CRUD / AI expand / AI deepen / history / export
- 未實作：provider 管理、agent session 工作流、多關係圖編輯、mainline / branch discipline
