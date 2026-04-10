from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.redis import RedisAdapter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = app.state.settings

    async with httpx.AsyncClient() as http_client:
        app.state.http_client = http_client

        engine = create_async_engine(
            settings.DATABASE_URL_asyncpg,
            echo=settings.DEBUG,
        )
        app.state.db_engine = engine
        app.state.async_session_maker = async_sessionmaker(
            engine, expire_on_commit=False
        )

        redis_adapter = RedisAdapter(settings)
        app.state.redis_adapter = redis_adapter

        try:
            yield
        finally:
            await redis_adapter.close()
            await engine.dispose()
