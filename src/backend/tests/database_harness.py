"""Explicit isolated-engine rebinding for tests that share the imported ASGI app."""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


_previous = None


def rebind_database(url: str) -> None:
    """Dispose the prior test engine, then atomically rebind app DB globals."""
    global _previous
    import db.database as database
    import main
    _previous=(database.DATABASE_URL,database.engine,database.async_session,main.engine,dict(main.app.dependency_overrides))
    asyncio.run(database.engine.dispose())
    engine = create_async_engine(url, echo=False)
    # Preserve the production SQLite connection policy on the replacement.
    from sqlalchemy import event
    @event.listens_for(engine.sync_engine, "connect")
    def sqlite_pragma(connection, _):
        cursor=connection.cursor();cursor.execute("PRAGMA foreign_keys=ON");cursor.close()
    database.DATABASE_URL=url
    database.engine=engine
    database.async_session=async_sessionmaker(engine,class_=AsyncSession,expire_on_commit=False)
    main.engine=engine
    # Routes imported these dependency callables by value; override both.
    from api.routes import get_db as api_get_db
    from agent_port.routes import get_db as agent_get_db
    async def isolated_db():
        async with database.async_session() as session: yield session
    main.app.dependency_overrides[api_get_db]=isolated_db
    main.app.dependency_overrides[agent_get_db]=isolated_db


def dispose_database() -> None:
    global _previous
    import db.database as database
    import main
    asyncio.run(database.engine.dispose())
    if _previous is not None:
        database.DATABASE_URL,database.engine,database.async_session,main.engine,overrides=_previous
        main.app.dependency_overrides.clear();main.app.dependency_overrides.update(overrides)
        _previous=None
