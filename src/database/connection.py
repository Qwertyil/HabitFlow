import logging
from collections.abc import AsyncGenerator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

logger = logging.getLogger("sqlalchemy.engine")


def get_engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.db_engine)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency injection для FastAPI
    """
    session_maker = request.app.state.async_session_maker
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
