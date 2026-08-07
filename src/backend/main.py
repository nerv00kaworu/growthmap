"""GrowthMap - 專案生長系統"""
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from db.database import engine, Base
from api.routes import router
from ai.routes import router as ai_router
from desktop.routes import router as desktop_router
from desktop.security import DesktopSessionMiddleware
from desktop.mutation_gate import DesktopMutationGateMiddleware
from desktop.startup_verdict import effective_entitlement
from desktop.migration_auth import authorized as migration_authorized
from desktop.secrets import desktop_mode
from agent_port.routes import router as agent_port_router, human_router as agent_port_human_router

STATIC_DIR = Path(os.getenv("GROWTHMAP_STATIC_DIR", Path(__file__).parent.parent / "frontend" / "out"))

# 安全邊界：CORS 必須是精確 origin allowlist；正式環境預設不允許跨站。
# 開發／測試僅開放本機 Editor 與 Player Web 的固定 origin，可用環境變數明確覆寫。
def _cors_allowed_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS")
    if configured is not None:
        return [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    if os.getenv("APP_ENV") in {"development", "test"}:
        return [
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ]
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    entitlement=effective_entitlement()
    # Fresh creation has no database object to evidence yet. Every existing
    # writable desktop database must carry Electron-generated startup evidence.
    if desktop_mode() and entitlement.mutations_allowed and not ((os.getenv("GROWTHMAP_FRESH_INSTALL")=="1" or os.getenv("GROWTHMAP_MIGRATION_REQUIRED")=="1" or os.getenv("GROWTHMAP_SCHEMA_CURRENT")=="1") and not Path(engine.url.database).exists()):
        from desktop.startup_database import verify_writable_startup
        await verify_writable_startup(engine,entitlement)
    extraction_startup=desktop_mode() and os.getenv("GROWTHMAP_FRESH_INSTALL") != "1" and not entitlement.mutations_allowed
    migration_required=desktop_mode() and os.getenv("GROWTHMAP_MIGRATION_REQUIRED") == "1"
    schema_current=desktop_mode() and os.getenv("GROWTHMAP_SCHEMA_CURRENT") == "1"
    if migration_required and not entitlement.mutations_allowed:
        raise RuntimeError("Desktop migration requires a verified pre-migration backup marker")
    database_absent=engine.url.get_backend_name()=="sqlite" and not Path(engine.url.database).exists()
    if desktop_mode() and entitlement.mutations_allowed and os.getenv("GROWTHMAP_FRESH_INSTALL") != "1" and not database_absent and not (migration_required or schema_current):
        raise RuntimeError("Desktop writable startup requires verified schema preflight")
    if extraction_startup:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("PRAGMA query_only=ON"))
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            integrity=(await conn.execute(__import__("sqlalchemy").text("PRAGMA quick_check"))).scalar()
            if integrity != "ok": raise RuntimeError("database integrity check failed")
        yield
        return
    if schema_current:
        async with engine.connect() as conn: await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        yield
        return
    # Authorize and consume immediately before opening the DDL transaction. The
    # marker is one-launch evidence: a failed launch must obtain a fresh marker/MAC.
    if migration_required and not migration_authorized():
        raise RuntimeError("Desktop migration requires a verified pre-migration backup marker")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            from db.migrations import migrate_sqlite
            await migrate_sqlite(conn)
    yield


app = FastAPI(
    title="GrowthMap",
    description="可視化專案生長系統 API",
    version="0.1.0-authoring.2",
    lifespan=lifespan,
)

# Added before other middleware so every desktop route, including readiness and
# static assets, requires the per-launch unguessable token.
app.add_middleware(DesktopMutationGateMiddleware)
app.add_middleware(DesktopSessionMiddleware)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "testserver"],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(agent_port_human_router, prefix="/api")
app.include_router(agent_port_router, prefix="/agent/v1")
if desktop_mode():
    app.include_router(desktop_router, prefix="/api")
else:
    @app.api_route("/api/desktop/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
    async def desktop_surface_absent(path: str):
        raise HTTPException(404, "Not Found")


@app.get("/api")
async def api_root():
    return {"name": "GrowthMap", "version": "0.1.0-authoring.2", "status": "running"}


@app.get("/api/health/deep")
async def deep_health():
    """Authoring-only readiness check; never mounts product runtime routes."""
    async with engine.connect() as conn:
        await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        if engine.url.get_backend_name() == "sqlite":
            integrity=(await conn.execute(__import__("sqlalchemy").text("PRAGMA quick_check"))).scalar()
            if integrity != "ok": raise HTTPException(503,"Database integrity check failed")
    return {"status": "ok", "surface": "authoring"}


# Serve static frontend if built
if STATIC_DIR.exists():
    # Mount _next and other static assets
    next_dir = STATIC_DIR / "_next"
    if next_dir.exists():
        app.mount("/_next", StaticFiles(directory=str(next_dir)), name="next_static")

    @app.get("/{path:path}")
    async def serve_spa(request: Request, path: str):
        # Resolve and verify containment to prevent path traversal
        file_path = (STATIC_DIR / path).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())):
            raise HTTPException(403, "Forbidden")
        # Try exact file first
        if file_path.is_file():
            return FileResponse(str(file_path))
        # Try path.html
        html_path = (STATIC_DIR / f"{path}.html").resolve()
        if str(html_path).startswith(str(STATIC_DIR.resolve())) and html_path.is_file():
            return FileResponse(str(html_path))
        # Fallback to index.html (SPA)
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "not found"}
else:
    @app.get("/")
    async def root():
        return {"name": "GrowthMap", "version": "0.1.0-authoring.2", "status": "running", "note": "Run 'npm run build' in frontend/ to serve UI"}
