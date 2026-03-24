# GrowthMap 工程規格 v0.1

---

## 1. DB Schema

### projects
```sql
CREATE TABLE projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    goal        TEXT DEFAULT '',
    root_node_id UUID,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'archived')),
    settings    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### nodes
```sql
CREATE TABLE nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    summary         TEXT DEFAULT '',
    node_type       TEXT NOT NULL DEFAULT 'idea'
                    CHECK (node_type IN (
                        'idea', 'concept', 'module', 'spec',
                        'task', 'decision', 'question', 'risk', 'resource'
                    )),
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'blocked', 'dormant', 'done', 'archived')),
    maturity        TEXT NOT NULL DEFAULT 'seed'
                    CHECK (maturity IN ('seed', 'rough', 'developing', 'stable', 'finalized')),
    priority        INTEGER DEFAULT 0,
    confidence      REAL DEFAULT 0.5,
    -- 內化欄位：直接在節點上的核心文字
    description     TEXT DEFAULT '',
    rules_text      TEXT DEFAULT '',
    constraints_text TEXT DEFAULT '',
    examples_text   TEXT DEFAULT '',
    questions_text  TEXT DEFAULT '',
    decision_notes  TEXT DEFAULT '',
    tags            TEXT[] DEFAULT '{}',
    -- 追蹤
    created_by      TEXT DEFAULT 'human',
    last_edited_by  TEXT DEFAULT 'human',
    position_x      REAL DEFAULT 0,
    position_y      REAL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_nodes_project ON nodes(project_id);
CREATE INDEX idx_nodes_type ON nodes(node_type);
CREATE INDEX idx_nodes_status ON nodes(status);
```

### edges
```sql
CREATE TABLE edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    from_node_id    UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    to_node_id      UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL DEFAULT 'child_of'
                    CHECK (relation_type IN (
                        'child_of', 'extends', 'depends_on', 'supports',
                        'alternative_to', 'refines', 'references', 'conflicts_with'
                    )),
    weight          REAL DEFAULT 1.0,
    note            TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_edges_project ON edges(project_id);
CREATE INDEX idx_edges_from ON edges(from_node_id);
CREATE INDEX idx_edges_to ON edges(to_node_id);
```

### content_blocks
```sql
CREATE TABLE content_blocks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id     UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    block_type  TEXT NOT NULL DEFAULT 'paragraph'
                CHECK (block_type IN (
                    'paragraph', 'bullet_list', 'rule_set', 'example',
                    'risk_note', 'decision_log', 'todo', 'prompt_context',
                    'code', 'quote', 'table'
                )),
    content     JSONB NOT NULL DEFAULT '{}',
    order_index INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT DEFAULT 'human',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_content_blocks_node ON content_blocks(node_id);
```

### suggestions
```sql
CREATE TABLE suggestions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    target_node_id  UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    action_type     TEXT NOT NULL
                    CHECK (action_type IN (
                        'expand_node', 'deepen_node', 'suggest_alternatives',
                        'detect_gaps', 'convert_to_spec', 'summarize'
                    )),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'rejected', 'edited')),
    payload         JSONB NOT NULL DEFAULT '{}',
    provider_id     TEXT DEFAULT '',
    provider_model  TEXT DEFAULT '',
    cost_estimate   REAL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     TEXT
);

CREATE INDEX idx_suggestions_node ON suggestions(target_node_id);
CREATE INDEX idx_suggestions_status ON suggestions(status);
```

### action_logs
```sql
CREATE TABLE action_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    node_id     UUID REFERENCES nodes(id) ON DELETE SET NULL,
    actor_type  TEXT NOT NULL CHECK (actor_type IN ('human', 'ai', 'agent', 'system')),
    actor_id    TEXT DEFAULT '',
    action_type TEXT NOT NULL,
    payload     JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_action_logs_project ON action_logs(project_id);
CREATE INDEX idx_action_logs_node ON action_logs(node_id);
```

### provider_configs
```sql
CREATE TABLE provider_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    provider_type   TEXT NOT NULL
                    CHECK (provider_type IN (
                        'cloud_api', 'local_model', 'external_agent',
                        'oauth_service', 'rules_engine'
                    )),
    endpoint        TEXT DEFAULT '',
    auth_type       TEXT DEFAULT 'none'
                    CHECK (auth_type IN ('api_key', 'oauth', 'none', 'local')),
    model_name      TEXT DEFAULT '',
    capabilities    TEXT[] DEFAULT '{}',
    cost_level      TEXT DEFAULT 'low'
                    CHECK (cost_level IN ('free', 'low', 'medium', 'high')),
    enabled         BOOLEAN DEFAULT true,
    settings        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### agent_sessions
```sql
CREATE TABLE agent_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    assigned_node_id    UUID REFERENCES nodes(id) ON DELETE SET NULL,
    assigned_branch_root_id UUID REFERENCES nodes(id) ON DELETE SET NULL,
    provider_id         UUID REFERENCES provider_configs(id),
    objective           TEXT DEFAULT '',
    mode                TEXT NOT NULL DEFAULT 'one_shot'
                        CHECK (mode IN ('one_shot', 'collab', 'background')),
    status              TEXT NOT NULL DEFAULT 'idle'
                        CHECK (status IN ('idle', 'running', 'awaiting_review', 'done', 'failed')),
    handoff_context     JSONB DEFAULT '{}',
    result_summary      TEXT DEFAULT '',
    last_heartbeat_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 2. TypeScript Types (前端共用)

```typescript
// === Core Types ===

type NodeType = 'idea' | 'concept' | 'module' | 'spec' | 'task' | 'decision' | 'question' | 'risk' | 'resource'
type NodeStatus = 'active' | 'blocked' | 'dormant' | 'done' | 'archived'
type NodeMaturity = 'seed' | 'rough' | 'developing' | 'stable' | 'finalized'
type RelationType = 'child_of' | 'extends' | 'depends_on' | 'supports' | 'alternative_to' | 'refines' | 'references' | 'conflicts_with'
type SuggestionStatus = 'pending' | 'accepted' | 'rejected' | 'edited'
type ActorType = 'human' | 'ai' | 'agent' | 'system'

interface Project {
  id: string
  name: string
  description: string
  goal: string
  rootNodeId: string | null
  status: 'active' | 'paused' | 'archived'
  settings: Record<string, any>
  createdAt: string
  updatedAt: string
}

interface GNode {
  id: string
  projectId: string
  title: string
  summary: string
  nodeType: NodeType
  status: NodeStatus
  maturity: NodeMaturity
  priority: number
  confidence: number
  description: string
  rulesText: string
  constraintsText: string
  examplesText: string
  questionsText: string
  decisionNotes: string
  tags: string[]
  createdBy: string
  lastEditedBy: string
  positionX: number
  positionY: number
  createdAt: string
  updatedAt: string
  // populated by API
  children?: GNode[]
  contentBlocks?: ContentBlock[]
}

interface Edge {
  id: string
  projectId: string
  fromNodeId: string
  toNodeId: string
  relationType: RelationType
  weight: number
  note: string
  createdAt: string
}

interface ContentBlock {
  id: string
  nodeId: string
  blockType: string
  content: any
  orderIndex: number
  createdBy: string
  createdAt: string
  updatedAt: string
}

interface Suggestion {
  id: string
  projectId: string
  targetNodeId: string
  actionType: string
  status: SuggestionStatus
  payload: any
  providerId: string
  providerModel: string
  costEstimate: number
  createdAt: string
  reviewedAt: string | null
  reviewedBy: string | null
}

interface ActionLog {
  id: string
  projectId: string
  nodeId: string | null
  actorType: ActorType
  actorId: string
  actionType: string
  payload: any
  createdAt: string
}
```

---

## 3. API Routes

### Projects
```
GET    /api/projects                    列出所有專案
POST   /api/projects                    建立專案
GET    /api/projects/:id                取得專案（含 root tree）
PATCH  /api/projects/:id                更新專案
DELETE /api/projects/:id                刪除專案
```

### Nodes
```
GET    /api/projects/:pid/nodes         列出節點（可帶 filter）
POST   /api/projects/:pid/nodes         建立節點
GET    /api/nodes/:id                   取得節點（含 children + content blocks）
PATCH  /api/nodes/:id                   更新節點
DELETE /api/nodes/:id                   刪除節點
POST   /api/nodes/:id/move              移動節點（改 parent）
GET    /api/nodes/:id/ancestors         取得祖先鏈
GET    /api/nodes/:id/subtree           取得完整子樹
```

### Edges
```
POST   /api/edges                       建立關聯
PATCH  /api/edges/:id                   更新關聯
DELETE /api/edges/:id                   刪除關聯
```

### Content Blocks
```
GET    /api/nodes/:nid/blocks           列出 content blocks
POST   /api/nodes/:nid/blocks           新增 block
PATCH  /api/blocks/:id                  更新 block
DELETE /api/blocks/:id                  刪除 block
POST   /api/nodes/:nid/blocks/reorder   重排 blocks
```

### AI Actions
```
POST   /api/nodes/:id/expand            延伸子節點
POST   /api/nodes/:id/deepen            內化節點
POST   /api/nodes/:id/alternatives      生成替代方向
POST   /api/nodes/:id/detect-gaps       偵測缺口
POST   /api/nodes/:id/summarize         壓縮摘要
POST   /api/nodes/:id/convert/spec      轉成規格
POST   /api/nodes/:id/convert/tasks     轉成任務群
```

### Suggestions
```
GET    /api/projects/:pid/suggestions   列出建議（可 filter status）
POST   /api/suggestions/:id/accept      接受建議
POST   /api/suggestions/:id/reject      拒絕建議
POST   /api/suggestions/:id/edit        修改後接受
POST   /api/suggestions/:id/regenerate  重新生成
```

### Agent Sessions
```
POST   /api/nodes/:id/assign-agent      指派 agent 接手
GET    /api/agent-sessions/:id          查看 session 狀態
POST   /api/agent-sessions/:id/steer    修正 agent 方向
POST   /api/agent-sessions/:id/stop     停止 session
```

### Providers
```
GET    /api/providers                   列出 providers
POST   /api/providers                   新增 provider
PATCH  /api/providers/:id               更新 provider
DELETE /api/providers/:id               刪除 provider
```

### Action Logs
```
GET    /api/projects/:pid/logs          查看操作歷史
GET    /api/nodes/:nid/logs             查看節點操作歷史
```

---

## 4. Provider Interface

```python
# backend/providers/base.py

from abc import ABC, abstractmethod
from typing import Any

class CognitionProvider(ABC):
    """所有認知來源的統一介面"""

    @abstractmethod
    def can_handle(self, action_type: str) -> bool:
        """是否支援此 action"""
        ...

    @abstractmethod
    def estimate_cost(self, action_type: str, context_size: int) -> float:
        """估算成本"""
        ...

    @abstractmethod
    async def run_action(self, request: ActionRequest) -> ActionResult:
        """執行 action"""
        ...

    @abstractmethod
    def normalize_output(self, raw: Any) -> dict:
        """統一輸出格式"""
        ...


class ActionRequest:
    action_type: str           # expand_node, deepen_node, etc.
    target_node: dict          # 當前節點
    ancestor_chain: list[dict] # 祖先路徑
    siblings: list[dict]       # 同層節點
    related_nodes: list[dict]  # 關聯節點
    project_summary: str       # 專案摘要
    project_goal: str          # 專案目標
    mode: str                  # divergent / convergent / organize
    constraints: list[str]     # 限制條件
    user_instructions: str     # 使用者附加指令
    desired_count: int         # 期望候選數量


class ActionResult:
    suggestions: list[dict]    # 候選結果
    metadata: dict             # provider 資訊、cost、model
    open_questions: list[str]  # 未決問題
```

---

## 5. Handoff Packet Format

```json
{
  "handoff_version": "0.1",
  "project": {
    "id": "uuid",
    "name": "Fate Origin Agent",
    "goal": "建立以八字+星盤驅動的角色生成遊戲系統",
    "summary": "..."
  },
  "target": {
    "node_id": "uuid",
    "title": "角色生成系統",
    "summary": "根據八字與星盤生成角色底層身份與初始屬性",
    "maturity": "rough",
    "current_content": { ... }
  },
  "ancestor_chain": [
    { "id": "...", "title": "Fate Origin Agent", "summary": "..." }
  ],
  "siblings": [
    { "id": "...", "title": "職業系統", "maturity": "developing" },
    { "id": "...", "title": "屬性系統", "maturity": "seed" }
  ],
  "children": [
    { "id": "...", "title": "八字輸入格式", "maturity": "rough" }
  ],
  "related_nodes": [ ... ],
  "objective": "補完角色生成規則骨架",
  "mode": "convergent",
  "constraints": [
    "非典型 build 合法，但需命理支持",
    "底層一旦鎖定不可回頭簡化"
  ],
  "output_expectations": {
    "types": ["child_nodes", "content_blocks", "open_questions"],
    "write_permission": "suggestion_only"
  }
}
```

---

## 6. Context Builder 邏輯

```python
# backend/context/builder.py

async def build_context(node_id: str, action_type: str) -> ActionRequest:
    """
    組裝給 provider 的上下文包
    原則：只給局部，不給整棵樹
    """
    node = await get_node(node_id)
    project = await get_project(node.project_id)

    # 祖先鏈（從 root 到 parent）
    ancestors = await get_ancestor_chain(node_id, max_depth=5)

    # 同層節點
    siblings = await get_siblings(node_id)

    # 子節點摘要
    children = await get_children_summary(node_id)

    # 關聯節點
    related = await get_related_nodes(node_id, max_count=10)

    # 計算 token budget
    # 祖先鏈只給 title+summary
    # 同層只給 title
    # 關聯只給 title+relation_type

    return ActionRequest(
        action_type=action_type,
        target_node=node.to_context_dict(),
        ancestor_chain=[a.to_brief_dict() for a in ancestors],
        siblings=[s.to_brief_dict() for s in siblings],
        related_nodes=[r.to_brief_dict() for r in related],
        project_summary=project.description,
        project_goal=project.goal,
        mode=infer_mode(node),        # 根據 maturity 推斷
        constraints=extract_constraints(node, ancestors),
        user_instructions='',
        desired_count=5
    )
```

---

*Phase 1 開工目標：Project + Node + Edge CRUD → 樹狀 GUI 顯示 → 基本節點編輯*
