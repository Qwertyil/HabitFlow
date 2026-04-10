from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import Settings, load_settings
from src.jobs.refresh_quotes import refresh_quotes

logger = logging.getLogger(__name__)

_DEFAULT_REFILL_INTERVAL_HOURS = 12

QuoteRefreshCallable = Callable[..., Awaitable[None]]


def schedule_quote_refresh_job(
    scheduler: AsyncIOScheduler,
    *,
    settings: Settings,
    http_client: httpx.AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
    refresh_job: QuoteRefreshCallable = refresh_quotes,
) -> None:
    scheduler.add_job(
        refresh_job,
        trigger="interval",
        hours=settings.REFILL_INTERVAL_HOURS or _DEFAULT_REFILL_INTERVAL_HOURS,
        kwargs={
            "settings": settings,
            "http_client": http_client,
            "session_maker": session_maker,
        },
        id="refresh_quotes_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def _install_shutdown_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:
            logger.debug("Signal handlers are not supported on this platform")
            return


async def run_quote_worker(
    settings: Settings | None = None,
    *,
    stop_event: asyncio.Event | None = None,
    scheduler_factory: Callable[[], AsyncIOScheduler] = AsyncIOScheduler,
    http_client_factory: Callable[[], httpx.AsyncClient] = httpx.AsyncClient,
    engine_factory: Callable[..., AsyncEngine] = create_async_engine,
    refresh_job: QuoteRefreshCallable = refresh_quotes,
) -> None:
    worker_settings = settings if settings is not None else load_settings()
    engine = engine_factory(
        worker_settings.DATABASE_URL_asyncpg,
        echo=worker_settings.DEBUG,
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    scheduler = scheduler_factory()
    worker_stop_event = stop_event if stop_event is not None else asyncio.Event()

    if stop_event is None:
        _install_shutdown_signal_handlers(worker_stop_event)

    scheduler_started = False

    try:
        async with http_client_factory() as http_client:
            schedule_quote_refresh_job(
                scheduler,
                settings=worker_settings,
                http_client=http_client,
                session_maker=session_maker,
                refresh_job=refresh_job,
            )
            scheduler.start()
            scheduler_started = True

            await refresh_job(
                settings=worker_settings,
                http_client=http_client,
                session_maker=session_maker,
            )
            await worker_stop_event.wait()
    finally:
        if scheduler_started:
            scheduler.shutdown(wait=False)
        await engine.dispose()
