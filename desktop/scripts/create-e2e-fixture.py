"""Create a canonical GrowthMap desktop DB fixture from production metadata/lifespan."""
import asyncio
import os
import sys
from pathlib import Path

output = Path(sys.argv[1]).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
os.environ["GROWTHMAP_DESKTOP_MODE"] = "1"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{output.as_posix()}"

# CI invokes this from desktop/. Put the production backend on the import path.
backend = Path(__file__).resolve().parents[2] / "src" / "backend"
sys.path.insert(0, str(backend))

from main import app, lifespan  # noqa: E402
from db.database import async_session  # noqa: E402
from models.models import Project  # noqa: E402


async def create():
    async with lifespan(app):
        async with async_session() as session:
            session.add(Project(id="fixture", name="Desktop Fixture", status="active"))
            await session.commit()


asyncio.run(create())
