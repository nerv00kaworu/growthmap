"""Project & Node API routes"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from models.models import ContentBlock, Node
from models.schemas import (
    ContentBlockCreate,
    ContentBlockOut,
    ContentBlockUpdate,
    EdgeCreate,
    EdgeOut,
    NodeBrief,
    NodeCreate,
    NodeOut,
    NodeUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from services import (
    NotFoundError,
    ValidationError,
    create_block as create_block_service,
    create_edge as create_edge_service,
    create_node as create_node_service,
    create_project as create_project_service,
    delete_edge as delete_edge_service,
    delete_node as delete_node_service,
    delete_project as delete_project_service,
    export_project_markdown,
    get_children as get_children_service,
    get_node as get_node_service,
    get_node_history as get_node_history_service,
    get_project as get_project_service,
    get_subtree as get_subtree_service,
    list_projects as list_projects_service,
    promote_child_mainline as promote_child_mainline_service,
    promote_mainline as promote_mainline_service,
    update_node as update_node_service,
    update_project as update_project_service,
)

router = APIRouter()


def _handle_service_error(exc: Exception) -> None:
    if isinstance(exc, NotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ValidationError):
        raise HTTPException(400, str(exc)) from exc
    raise exc


# ─── Projects ───


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    return await list_projects_service(db)


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    return await create_project_service(db, data)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await get_project_service(db, project_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, data: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    try:
        return await update_project_service(db, project_id, data)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await delete_project_service(db, project_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


# ─── Nodes ───


@router.get("/projects/{project_id}/nodes", response_model=list[NodeBrief])
async def list_nodes(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Node).where(Node.project_id == project_id).order_by(Node.created_at))
    return result.scalars().all()


@router.post("/projects/{project_id}/nodes", response_model=NodeOut, status_code=201)
async def create_node(project_id: str, data: NodeCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_node_service(db, project_id, data)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.get("/nodes/{node_id}", response_model=NodeOut)
async def get_node(node_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await get_node_service(db, node_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
async def update_node(node_id: str, data: NodeUpdate, db: AsyncSession = Depends(get_db)):
    try:
        return await update_node_service(db, node_id, data)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(node_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await delete_node_service(db, node_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.get("/nodes/{node_id}/children", response_model=list[NodeBrief])
async def get_children(node_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await get_children_service(db, node_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.get("/nodes/{node_id}/subtree")
async def get_subtree(node_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await get_subtree_service(db, node_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


# ─── Edges ───


@router.post("/edges", response_model=EdgeOut, status_code=201)
async def create_edge(data: EdgeCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_edge_service(db, data)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.post("/edges/{edge_id}/promote-mainline", response_model=EdgeOut)
async def promote_mainline(edge_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await promote_mainline_service(db, edge_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.post("/nodes/{parent_id}/promote-child/{child_id}")
async def promote_child_mainline(parent_id: str, child_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await promote_child_mainline_service(db, parent_id, child_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(edge_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await delete_edge_service(db, edge_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


# ─── Content Blocks ───


@router.get("/nodes/{node_id}/blocks", response_model=list[ContentBlockOut])
async def list_blocks(node_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ContentBlock).where(ContentBlock.node_id == node_id).order_by(ContentBlock.order_index)
    )
    return result.scalars().all()


@router.post("/nodes/{node_id}/blocks", response_model=ContentBlockOut, status_code=201)
async def create_block(node_id: str, data: ContentBlockCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_block_service(db, node_id, data)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)


@router.patch("/blocks/{block_id}", response_model=ContentBlockOut)
async def update_block(block_id: str, data: ContentBlockUpdate, db: AsyncSession = Depends(get_db)):
    block = await db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(block, key, value)
    await db.commit()
    await db.refresh(block)
    return block


@router.delete("/blocks/{block_id}", status_code=204)
async def delete_block(block_id: str, db: AsyncSession = Depends(get_db)):
    block = await db.get(ContentBlock, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    await db.delete(block)
    await db.commit()


# ─── Node History ───


@router.get("/nodes/{node_id}/history")
async def get_node_history(node_id: str, limit: int = 20, db: AsyncSession = Depends(get_db)):
    return await get_node_history_service(db, node_id, limit)


# ─── Export ───


@router.get("/projects/{project_id}/export", response_class=PlainTextResponse)
async def export_project(project_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await export_project_markdown(db, project_id)
    except (NotFoundError, ValidationError) as exc:
        _handle_service_error(exc)
