"""AI growth routes — expand & deepen nodes via LLM"""
import json
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Literal, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from ai.providers import LLMConfig, get_provider
from ai.context import build_node_context
from models.models import ActionLog, Node, ProviderConfig
from models.schemas import validate_app_secret_env_key
from desktop.secrets import desktop_mode, get as get_desktop_secret
from ai.provider import parse_json_response  # Reuse existing JSON parser

router = APIRouter(prefix="/ai", tags=["ai"])


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpandRequest(StrictRequest):
    node_id: str
    instruction: Optional[str] = None
    count: int = 3  # how many suggestions
    mode: Literal["focused", "explore", "challenge"] = "explore"
    provider_id: str
    locale: Literal["zh-TW", "zh-CN", "en"] = "zh-TW"


class DeepenRequest(StrictRequest):
    node_id: str
    instruction: Optional[str] = None
    provider_id: str
    locale: Literal["zh-TW", "zh-CN", "en"] = "zh-TW"


class TestConnectionRequest(StrictRequest):
    provider_id: str


class TestConnectionResponse(BaseModel):
    ok: bool
    provider: str
    model: Optional[str] = None
    message: str


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


AI_FRAMEWORK = {
    "en": {
        "expand_system": "You are a project-structure analyst. Use the complete ancestor path, existing children, siblings, summaries, and content blocks. Suggest distinct, concrete child nodes within the current node's scope. Never duplicate existing or semantically equivalent nodes. Return only a JSON array of objects with title, summary, and node_type (idea, concept, task, question, decision, risk, resource, note, or module). Each summary must contain actionable detail; use a question when facts are uncertain. Write all generated text in English.",
        "deepen_system": "You are a knowledge-development analyst. Use the complete ancestor path, operation history, and existing content. Preserve the node's direction and produce a stronger enriched_summary plus 2–4 new, non-duplicative content_blocks. Return only JSON with enriched_summary and content_blocks containing title, body, and block_type. Be concrete and testable; use questions rather than inventing uncertain facts. Write all generated text in English.",
        "chat_system": "You are a project advisor. Use the complete ancestor context and existing content. Be concrete and constructive; identify issues, alternatives, and clarifications. Write all generated text in English.",
        "modes": {"focused":"Focused: fill essential structural gaps without drifting from the main line.","explore":"Explore: examine strongly related adjacent space and uncovered dimensions.","challenge":"Challenge: surface alternatives, counterexamples, risks, constraints, and opposing views."},
        "children":"Existing child titles; do not duplicate", "siblings":"Existing sibling titles; do not duplicate",
        "instruction":"User instruction", "question":"Current user question", "history":"Conversation history", "user":"User", "assistant":"Advisor",
    },
    "zh-CN": {
        "expand_system": "你是项目结构分析师。请结合完整祖先路径、现有子节点、兄弟节点、摘要和内容区块，在当前节点范围内提出互不重复、具体可执行的子节点。不得与已有节点重复或语义相同。仅返回 JSON 数组，每项包含 title、summary、node_type；node_type 只能是 idea、concept、task、question、decision、risk、resource、note 或 module。不确定时请提出具体问题。所有生成内容必须使用简体中文。",
        "deepen_system": "你是知识深化分析师。请结合完整祖先路径、操作历史和现有内容，在不改变节点核心方向的前提下完善 enriched_summary，并新增 2 至 4 个不重复的 content_blocks。仅返回 JSON；每个区块包含 title、body、block_type。内容必须具体且可验证；不确定时提出问题，不得编造。所有生成内容必须使用简体中文。",
        "chat_system": "你是项目顾问。请结合完整祖先上下文和现有内容，提供具体、有建设性的回答，并指出问题、替代方案和需要澄清之处。所有生成内容必须使用简体中文。",
        "modes": {"focused":"聚焦主线：补齐必要结构、步骤和基础组件，不要偏离主题。","explore":"探索延伸：探索紧密相关的相邻方向和未覆盖方面。","challenge":"挑战假设：提出替代方案、反例、风险、限制和对立观点。"},
        "children":"已有子节点标题；禁止重复", "siblings":"已有兄弟节点标题；禁止重复",
        "instruction":"用户指示", "question":"用户当前问题", "history":"对话历史", "user":"用户", "assistant":"顾问",
    },
    "zh-TW": {
        "expand_system": "你是專案結構分析師。請結合完整祖先路徑、現有子節點、兄弟節點、摘要和內容區塊，在目前節點範圍內提出互不重複、具體可執行的子節點。不得與已有節點重複或語義相同。只回傳 JSON 陣列，每項包含 title、summary、node_type；node_type 只能是 idea、concept、task、question、decision、risk、resource、note 或 module。不確定時請提出具體問題。所有生成內容必須使用繁體中文。",
        "deepen_system": "你是知識深化分析師。請結合完整祖先路徑、操作歷史和現有內容，在不改變節點核心方向的前提下完善 enriched_summary，並新增 2 至 4 個不重複的 content_blocks。只回傳 JSON；每個區塊包含 title、body、block_type。內容必須具體且可驗證；不確定時提出問題，不得捏造。所有生成內容必須使用繁體中文。",
        "chat_system": "你是專案顧問。請結合完整祖先上下文和現有內容，提供具體、有建設性的回答，並指出問題、替代方案和需要釐清之處。所有生成內容必須使用繁體中文。",
        "modes": {"focused":"聚焦主線：補齊必要結構、步驟和基礎元件，不要偏離主題。","explore":"探索延伸：探索緊密相關的相鄰方向和未覆蓋面向。","challenge":"挑戰假設：提出替代方案、反例、風險、限制和對立觀點。"},
        "children":"已有子節點標題；禁止重複", "siblings":"已有兄弟節點標題；禁止重複",
        "instruction":"使用者指示", "question":"使用者目前問題", "history":"對話歷史", "user":"使用者", "assistant":"顧問",
    },
}

def _framework(locale: str) -> dict:
    return AI_FRAMEWORK[locale]

def _prompt_payload(context: dict, **fields) -> str:
    # User/model data is isolated as JSON instead of interpolated into framework prose.
    return json.dumps({"context": context, **fields}, ensure_ascii=False, indent=2)

def get_expand_mode_prompt(mode: Literal["focused", "explore", "challenge"], locale: str = "zh-TW") -> str:
    return _framework(locale)["modes"][mode]


async def _to_llm_config(provider_id: str, db: AsyncSession) -> tuple[LLMConfig, str]:
    """Resolve one enabled server-side provider profile; requests cannot override secrets/endpoints."""
    provider_config = await db.get(ProviderConfig, provider_id)
    if not provider_config or not provider_config.enabled:
        raise ValueError("Selected provider is unavailable")
    validate_app_secret_env_key(provider_config.secret_env_key)
    # Desktop BYOK has a strict process-memory boundary. Never fall back to an
    # inherited environment key, even when an identically named variable exists.
    api_key = get_desktop_secret(provider_config.id) if desktop_mode() else os.getenv(provider_config.secret_env_key)
    if provider_config.provider_type != "mock" and not api_key:
        source = "desktop secure storage" if desktop_mode() else f"environment variable {provider_config.secret_env_key}"
        raise ValueError(f"API key is not configured in {source}")
    return LLMConfig(
        provider=provider_config.provider_type,
        api_key=api_key,
        base_url=provider_config.endpoint or None,
        model=provider_config.model_name or None,
    ), provider_config.id

@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(req: TestConnectionRequest, db: AsyncSession = Depends(get_db)):
    """Test an existing server-side provider profile without accepting secret overrides."""
    try:
        config, _ = await _to_llm_config(req.provider_id, db)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    from ai.providers.registry import test_connection as test_conn
    return TestConnectionResponse(**(await test_conn(config)))


@router.post("/expand", response_model=ExpandResponse)
async def expand_node(req: ExpandRequest, db: AsyncSession = Depends(get_db)):
    """讓 LLM 為節點生成子節點建議（候選，不直接寫入）"""
    try:
        ctx = await build_node_context(req.node_id, db)
    except ValueError as e:
        raise HTTPException(404, str(e))

    existing_children = [c["title"] for c in ctx["children"]]
    existing_siblings = [s["title"] for s in ctx["siblings"]]
    frame = _framework(req.locale)
    user_prompt = _prompt_payload(
        ctx,
        mode=get_expand_mode_prompt(req.mode, req.locale),
        requested_count=req.count,
        existing_children={"label": frame["children"], "titles": existing_children},
        existing_siblings={"label": frame["siblings"], "titles": existing_siblings},
        instruction={"label": frame["instruction"], "value": req.instruction},
    )

    try:
        llm_cfg, provider_id = await _to_llm_config(req.provider_id, db)
        provider = get_provider(llm_cfg)
        raw = await provider.complete(frame["expand_system"], user_prompt, model=llm_cfg.model)
            
        suggestions = parse_json_response(raw)
        if not isinstance(suggestions, list):
            raise ValueError("LLM returned an invalid suggestions payload")

        # Validate each suggestion structure
        validated = []
        for s in suggestions:
            if not isinstance(s, dict):
                raise TypeError("Each suggestion must be an object")
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
                payload={"count": len(validated), "instruction": req.instruction, "mode": req.mode, "provider_id": provider_id, "model": llm_cfg.model, "outcome": "success"},
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
    except TypeError as e:
        raise HTTPException(500, f"LLM returned malformed expand payload: {str(e)}")
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

    frame = _framework(req.locale)
    user_prompt = _prompt_payload(
        ctx,
        instruction={"label": frame["instruction"], "value": req.instruction},
    )

    try:
        llm_cfg, provider_id = await _to_llm_config(req.provider_id, db)
        provider = get_provider(llm_cfg)
        raw = await provider.complete(frame["deepen_system"], user_prompt, model=llm_cfg.model)
            
        result = parse_json_response(raw)
        if not isinstance(result, dict):
            raise ValueError("LLM returned an invalid deepen payload")

        enriched_summary = result["enriched_summary"]
        content_blocks = result.get("content_blocks", [])
        if not isinstance(enriched_summary, str):
            raise TypeError("enriched_summary must be a string")
        if not isinstance(content_blocks, list):
            raise TypeError("content_blocks must be a list")
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
                payload={"instruction": req.instruction, "blocks_generated": len(content_blocks), "provider_id": provider_id, "model": llm_cfg.model, "outcome": "success"},
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
    except TypeError as e:
        raise HTTPException(500, f"LLM returned malformed deepen payload: {str(e)}")
    except ValueError as e:
        raise HTTPException(500, f"LLM error: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"LLM error: {str(e)}")


# ─── Chat ───

class ChatRequest(StrictRequest):
    node_id: str
    message: str
    history: list[dict] = []
    provider_id: str
    locale: Literal["zh-TW", "zh-CN", "en"] = "zh-TW"


class ChatResponse(BaseModel):
    reply: str
    context_used: dict


@router.post("/chat", response_model=ChatResponse)
async def chat_node(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """與節點進行對話，LLM 作為專案顧問回應。"""
    try:
        ctx = await build_node_context(req.node_id, db)
    except ValueError as e:
        raise HTTPException(404, str(e))

    frame = _framework(req.locale)
    system_prompt = frame["chat_system"]
    history = [
        {"role": frame["user"] if h.get("role") == "user" else frame["assistant"], "content": h.get("content", "")}
        for h in req.history
    ]
    context_summary = _prompt_payload(
        ctx,
        history={"label": frame["history"], "messages": history},
        question={"label": frame["question"], "value": req.message},
    )

    try:
        llm_cfg, provider_id = await _to_llm_config(req.provider_id, db)
        provider = get_provider(llm_cfg)
        reply = await provider.complete(system_prompt, context_summary, model=llm_cfg.model)

        node = await db.get(Node, req.node_id)
        if node:
            db.add(ActionLog(
                project_id=node.project_id,
                node_id=req.node_id,
                actor_type="ai",
                action_type="ai_chat",
                payload={"message": req.message[:200], "reply": reply[:200], "provider_id": provider_id, "model": llm_cfg.model, "outcome": "success"},
            ))
            await db.commit()

        return ChatResponse(
            reply=reply,
            context_used={"ancestor_path": ctx["ancestor_path"], "node_title": ctx["current_node"]["title"]},
        )
    except Exception as e:
        raise HTTPException(500, f"Chat error: {str(e)}")