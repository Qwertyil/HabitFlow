from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from src.config import settings
from src.jobs.refresh_quotes import refresh_quotes_job


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    async with httpx.AsyncClient() as http_client:
        app.state.http_client = http_client

        scheduler = AsyncIOScheduler()
        app.state.scheduler = scheduler

        if getattr(settings, "TESTING", False):
            yield
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
