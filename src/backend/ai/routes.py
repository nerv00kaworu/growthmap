"""AI growth routes — expand & deepen nodes via LLM"""
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from ai.provider import llm_complete, parse_json_response
from ai.context import build_node_context
from models.models import ActionLog, Node

router = APIRouter(prefix="/ai", tags=["ai"])


class ExpandRequest(BaseModel):
    node_id: str
    instruction: Optional[str] = None
    count: int = 3  # how many suggestions
    mode: Literal["focused", "explore", "challenge"] = "explore"
    provider_id: Optional[str] = None


class DeepenRequest(BaseModel):
    node_id: str
    instruction: Optional[str] = None
    provider_id: Optional[str] = None


class Suggestion(BaseModel):
    title: str
    summary: str
    node_type: str


class ExpandResponse(BaseModel):
    suggestions: list[Suggestion]
    context_used: dict


class DeepenResponse(BaseModel):
    enriched_summary: str
    content_blocks: list[dict]
    context_used: dict


EXPAND_SYSTEM = """你是一個專案結構分析師。根據提供的上下文，為指定節點生成子節點建議。

規則：
1. 只基於當前節點的範圍延伸，不要跳出主題
2. **嚴禁重複**：下方會列出「已有子節點」與「兄弟節點」的標題清單，你的建議不得與它們重複或語義相同
3. 每個建議要有明確的標題和簡短摘要
4. node_type 從以下選擇：idea, concept, task, question, decision, risk, resource, note, module
5. 建議應該互相互補，覆蓋不同面向
6. 每個建議的標題必須彼此不同，禁止生成多個相同或近似的建議

回傳格式（純 JSON，不要 markdown）：
[
  {"title": "...", "summary": "...", "node_type": "..."},
  ...
]"""

DEEPEN_SYSTEM = """你是一個知識深化分析師。根據提供的上下文，對指定節點進行內容深化。

規則：
1. 不要改變節點的核心方向，而是充實其內容
2. 提供更完善的摘要（在現有摘要的基礎上擴充，不要丟棄已有的好內容）
3. 生成 2-4 個**新的**內容塊（content blocks），每個塊有明確主題
4. **累積而非覆蓋**：上下文中會包含已有的 content_blocks，你的新建議應該補充尚未涵蓋的面向，不要重複已有的區塊
5. block_type 從以下選擇：definition, rules, examples, constraints, decisions, notes, references, questions
6. 內容要具體，不要空泛
7. 參考此節點的操作歷史（recent_history），了解它經歷過什麼演化

回傳格式（純 JSON，不要 markdown）：
{
  "enriched_summary": "更完整的摘要（在原有基礎上擴充）...",
  "content_blocks": [
    {"title": "...", "body": "...", "block_type": "..."},
    ...
  ]
}"""


def get_expand_mode_prompt(mode: Literal["focused", "explore", "challenge"]) -> str:
    prompts = {
        "focused": "模式：focused（聚焦主線）。請優先補齊當前節點缺失的核心結構、必要步驟與基礎元件，避免跳到太遠的主題。",
        "explore": "模式：explore（探索延伸）。請保持與主題強關聯，但主動探索相鄰空間、未覆蓋面向與可擴張支線，避免結果過早定型。",
        "challenge": "模式：challenge（挑戰假設）。請優先提出會打破僵化的替代方向、反例、風險、限制與對立觀點，至少有一個建議應直接質疑當前思路。",
    }
    return prompts[mode]


@router.post("/expand", response_model=ExpandResponse)
async def expand_node(req: ExpandRequest, db: AsyncSession = Depends(get_db)):
    """讓 LLM 為節點生成子節點建議（候選，不直接寫入）"""
    try:
        ctx = await build_node_context(req.node_id, db)
    except ValueError as e:
        raise HTTPException(404, str(e))

    existing_children = [c["title"] for c in ctx["children"]]
    existing_siblings = [s["title"] for s in ctx["siblings"]]
    dedup_block = ""
    if existing_children:
        dedup_block += f"\n已有子節點（禁止重複）：{', '.join(existing_children)}"
    if existing_siblings:
        dedup_block += f"\n已有兄弟節點（禁止重複）：{', '.join(existing_siblings)}"

    user_prompt = f"""專案上下文：
{json.dumps(ctx, ensure_ascii=False, indent=2)}
{dedup_block}

{get_expand_mode_prompt(req.mode)}

請為節點「{ctx['current_node']['title']}」生成 {req.count} 個**不重複**的子節點建議。
{"使用者指示：" + req.instruction if req.instruction else ""}"""

    try:
        raw = await llm_complete(EXPAND_SYSTEM, user_prompt, provider_id=req.provider_id, db=db)
        suggestions = parse_json_response(raw)
        if not isinstance(suggestions, list):
            raise ValueError("LLM returned an invalid suggestions payload")

        # Validate required fields before constructing response
        validated = []
        for s in suggestions:
            if not isinstance(s, dict):
                raise TypeError("Each suggestion payload must be an object")
            validated.append(Suggestion(
                title=s["title"],
                summary=s["summary"],
                node_type=s["node_type"],
            ))

        # Log the AI operation
        node = await db.get(Node, req.node_id)
        if node:
            db.add(ActionLog(
                project_id=node.project_id,
                node_id=req.node_id,
                actor_type="ai",
                action_type="ai_expand",
                payload={"count": len(validated), "instruction": req.instruction, "mode": req.mode},
            ))
            await db.commit()

        return ExpandResponse(
            suggestions=validated,
            context_used={"ancestor_path": ctx["ancestor_path"], "siblings_count": len(ctx["siblings"]), "children_count": len(ctx["children"]), "mode": req.mode},
        )
    except json.JSONDecodeError:
        raise HTTPException(500, "LLM returned invalid JSON for expand")
    except KeyError as e:
        raise HTTPException(500, f"LLM returned incomplete expand payload: missing {str(e)}")
    except TypeError:
        raise HTTPException(500, "LLM returned malformed expand payload")
    except ValueError as e:
        raise HTTPException(500, f"LLM error: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"LLM error: {str(e)}")


@router.post("/deepen", response_model=DeepenResponse)
async def deepen_node(req: DeepenRequest, db: AsyncSession = Depends(get_db)):
    """讓 LLM 深化節點內容（候選，不直接寫入）"""
    try:
        ctx = await build_node_context(req.node_id, db)
    except ValueError as e:
        raise HTTPException(404, str(e))

    user_prompt = f"""專案上下文：
{json.dumps(ctx, ensure_ascii=False, indent=2)}

請深化節點「{ctx['current_node']['title']}」的內容。
{"使用者指示：" + req.instruction if req.instruction else ""}"""

    try:
        raw = await llm_complete(DEEPEN_SYSTEM, user_prompt, provider_id=req.provider_id, db=db)
        result = parse_json_response(raw)
        if not isinstance(result, dict):
            raise ValueError("LLM returned an invalid deepen payload")

        enriched_summary = result["enriched_summary"]
        content_blocks = result.get("content_blocks", [])
        if not isinstance(enriched_summary, str):
            raise TypeError("enriched_summary must be a string")
        if not isinstance(content_blocks, list):
            raise TypeError("content_blocks must be a list")

        # Validate content_blocks structure
        for block in content_blocks:
            if not isinstance(block, dict) or "title" not in block or "body" not in block:
                raise TypeError(f"Invalid content block structure: {block}")

        # Log the AI operation
        node = await db.get(Node, req.node_id)
        if node:
            db.add(ActionLog(
                project_id=node.project_id,
                node_id=req.node_id,
                actor_type="ai",
                action_type="ai_deepen",
                payload={"instruction": req.instruction, "blocks_generated": len(content_blocks)},
            ))
            await db.commit()

        return DeepenResponse(
            enriched_summary=enriched_summary,
            content_blocks=content_blocks,
            context_used={"ancestor_path": ctx["ancestor_path"], "siblings_count": len(ctx["siblings"]), "children_count": len(ctx["children"])},
        )
    except json.JSONDecodeError:
        raise HTTPException(500, "LLM returned invalid JSON for deepen")
    except KeyError as e:
        raise HTTPException(500, f"LLM returned incomplete deepen payload: missing {str(e)}")
    except TypeError:
        raise HTTPException(500, "LLM returned malformed deepen payload")
    except ValueError as e:
        raise HTTPException(500, f"LLM error: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"LLM error: {str(e)}")
