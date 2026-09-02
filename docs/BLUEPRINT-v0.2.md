> **Historical record.** This document describes its own stated baseline/source-security record and is **not** current release or deployment guidance. See the [root README](../README.md) and [current release evidence](RELEASE-EVIDENCE.md).

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
- Provider: 可插拔認知層（目前 MVP 提供 Mock 與 OpenAI-compatible adapter；連線設定由前端 localStorage 隨請求送出，尚未持久化到後端）

## 開發順序
- Phase 1: 核心骨架 (Project/Node/Edge + GUI + CRUD)
- Phase 2: AI 生長 (Suggestion + expand/deepen + provider)
- Phase 3: 共構能力 (agent handoff + session + history)
- Phase 4: 智能路由 (cost routing + fallback)

## 與目前 MVP 的落差

- 已實作：Project / Node / `child_of` Edge / tree-first GUI / CRUD / content blocks / mainline selection / proposal branches（建立、切換、合併、封存）/ AI expand、deepen、chat / history / Markdown、JSON、spec export
- 部分實作：非 `child_of` edge 的儲存與 API 存在，但尚無通用視覺編輯與治理流程
- 已實作（Core Collaboration v1）：人工 Agent Sessions、provider-neutral `/agent/v1`、有限期 scoped grants、proposal/direct atomic batch、revision conflict、context/readback、REST thin CLI/MCP 與最小可審核 GUI。
- 未實作：完整跨關係圖視覺治理、一般化 agent batch undo、成本路由/fallback。Agent Port 不執行 provider/model。
