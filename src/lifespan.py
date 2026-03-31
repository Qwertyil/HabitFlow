from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jobs.refresh_quotes import refresh_quotes_job
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

        scheduler = AsyncIOScheduler()
        app.state.scheduler = scheduler

        if settings.TESTING:
            try:
                yield
            finally:
                await redis_adapter.close()
                await engine.dispose()
            return

        scheduler.add_job(
            refresh_quotes_job,
            trigger="interval",
            hours=settings.REFILL_INTERVAL_HOURS
            if settings.REFILL_INTERVAL_HOURS
            else 12,
            kwargs={"app": app},
            id="refresh_quotes_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        scheduler.start()
        await refresh_quotes_job(app)

        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            await redis_adapter.close()
            await engine.dispose()
