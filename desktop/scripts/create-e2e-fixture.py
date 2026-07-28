"""Create a canonical GrowthMap DB fixture in an isolated E2E temp directory."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path


def fixture_output(argument: str) -> Path:
    output = Path(argument).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not output.is_relative_to(temp_root):
        raise SystemExit("E2E fixture path must be inside the system temp directory")
    if not output.name.startswith("fixture") or output.suffix.lower() not in {".db", ".sqlite"}:
        raise SystemExit("E2E fixture filename must start with 'fixture' and end in .db or .sqlite")
    if output.exists():
        raise SystemExit("E2E fixture output must be a fresh path")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


if len(sys.argv) != 2:
    raise SystemExit("usage: create-e2e-fixture.py TEMP_FIXTURE_PATH")
output = fixture_output(sys.argv[1])
os.environ["GROWTHMAP_DESKTOP_MODE"] = "1"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{output.as_posix()}"

# CI invokes this from desktop/. Put the production backend on the import path.
backend = Path(__file__).resolve().parents[2] / "src" / "backend"
sys.path.insert(0, str(backend))

from db.database import Base, async_session, engine  # noqa: E402
from models.models import Project  # noqa: E402,F401 -- registers canonical metadata


async def create():
    # Fixture setup owns schema initialization. Production startup remains subject
    # to its normal query-only and migration-authorization gates.
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        session.add(Project(id="fixture", name="Desktop Fixture", status="active"))
        await session.commit()
    await engine.dispose()


asyncio.run(create())
