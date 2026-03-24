"""GrowthMap - 專案生長系統"""
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from db.database import engine, Base
from api.routes import router
from ai.routes import router as ai_router

STATIC_DIR = Path(__file__).parent.parent / "frontend" / "out"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="GrowthMap",
    description="可視化專案生長系統 API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(ai_router, prefix="/api")


@app.get("/api")
async def api_root():
    return {"name": "GrowthMap", "version": "0.1.0", "status": "running"}


# Serve static frontend if built
if STATIC_DIR.exists():
    # Mount _next and other static assets
    next_dir = STATIC_DIR / "_next"
    if next_dir.exists():
        app.mount("/_next", StaticFiles(directory=str(next_dir)), name="next_static")

    @app.get("/{path:path}")
    async def serve_spa(request: Request, path: str):
        # Try exact file first
        file_path = STATIC_DIR / path
        if file_path.is_file():
            return FileResponse(str(file_path))
        # Try path.html
        html_path = STATIC_DIR / f"{path}.html"
        if html_path.is_file():
            return FileResponse(str(html_path))
        # Fallback to index.html (SPA)
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "not found"}
else:
    @app.get("/")
    async def root():
        return {"name": "GrowthMap", "version": "0.1.0", "status": "running", "note": "Run 'npm run build' in frontend/ to serve UI"}
