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
        # Lightweight SQLite migrations for databases created before these columns existed.
        for statement in (
            "ALTER TABLE nodes ADD COLUMN branch_id VARCHAR(36) REFERENCES branches(id)",
            "ALTER TABLE nodes ADD COLUMN workflow_status VARCHAR(20) NOT NULL DEFAULT 'draft'",
            "ALTER TABLE nodes ADD COLUMN file_paths JSON DEFAULT '[]'",
            "ALTER TABLE provider_configs ADD COLUMN secret_env_key VARCHAR(128) DEFAULT ''",
        ):
            try:
                await conn.execute(__import__("sqlalchemy").text(statement))
            except Exception:
                pass  # Column already exists on current databases

        # 新資料必須永遠可被 EdgeOut 序列化；既有 NULL 由讀取端相容，不在啟動時改寫專案資料。
        # SQLite 的 partial unique index 僅在目前資料無衝突時建立；若舊專案有髒資料，服務仍可啟動，
        # API 寫入路徑會先維持唯一主線，待該專案經人工裁決後即可建立硬約束。
        try:
            await conn.execute(__import__("sqlalchemy").text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_edges_one_mainline_per_parent "
                "ON edges(from_node_id) "
                "WHERE relation_type = 'child_of' AND is_mainline = 1"
            ))
        except Exception:
            pass

        # 舊庫即使已有多主線而暫時無法建立 unique index，也要立刻阻止新的衝突寫入。
        for statement in (
            """
            CREATE TRIGGER IF NOT EXISTS trg_edges_one_mainline_insert
            BEFORE INSERT ON edges
            WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1
            BEGIN
              SELECT RAISE(ABORT, 'duplicate mainline for parent')
              WHERE EXISTS (
                SELECT 1 FROM edges
                WHERE from_node_id = NEW.from_node_id
                  AND relation_type = 'child_of'
                  AND is_mainline = 1
              );
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_edges_one_mainline_update
            BEFORE UPDATE OF from_node_id, relation_type, is_mainline ON edges
            WHEN NEW.relation_type = 'child_of' AND NEW.is_mainline = 1
            BEGIN
              SELECT RAISE(ABORT, 'duplicate mainline for parent')
              WHERE EXISTS (
                SELECT 1 FROM edges
                WHERE from_node_id = NEW.from_node_id
                  AND relation_type = 'child_of'
                  AND is_mainline = 1
                  AND id != OLD.id
              );
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_edges_normalize_null_insert
            AFTER INSERT ON edges
            WHEN NEW.weight IS NULL OR NEW.note IS NULL
            BEGIN
              UPDATE edges
              SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '')
              WHERE id = NEW.id;
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_edges_normalize_null_update
            AFTER UPDATE OF weight, note ON edges
            WHEN NEW.weight IS NULL OR NEW.note IS NULL
            BEGIN
              UPDATE edges
              SET weight = COALESCE(weight, 1.0), note = COALESCE(note, '')
              WHERE id = NEW.id;
            END
            """,
        ):
            await conn.execute(__import__("sqlalchemy").text(statement))
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
