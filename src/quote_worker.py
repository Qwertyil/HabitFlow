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

    def _request_shutdown(signal_name: str) -> None:
        logger.info(
            "Shutdown signal received",
            extra={
                "event": "quote_worker_shutdown_signal_received",
                "signal": signal_name,
            },
        )
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, _request_shutdown, signum.name)
        except NotImplementedError:
            logger.debug(
                "Signal handlers are not supported on this platform",
                extra={"event": "quote_worker_signal_handlers_unsupported"},
            )
            return

    logger.debug(
        "Shutdown signal handlers installed",
        extra={
            "event": "quote_worker_signal_handlers_installed",
            "signals": [signal.SIGINT.name, signal.SIGTERM.name],
        },
    )


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
        echo=False,
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    scheduler = scheduler_factory()
    worker_stop_event = stop_event if stop_event is not None else asyncio.Event()

    if stop_event is None:
        _install_shutdown_signal_handlers(worker_stop_event)

    scheduler_started = False

    try:
        logger.info(
            "Quote worker starting",
            extra={
                "event": "quote_worker_starting",
                "refresh_interval_hours": (
                    worker_settings.REFILL_INTERVAL_HOURS
                    or _DEFAULT_REFILL_INTERVAL_HOURS
                ),
            },
        )
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
            logger.info(
                "Quote refresh scheduler started",
                extra={
                    "event": "quote_worker_scheduler_started",
                    "job_id": "refresh_quotes_job",
                },
            )

            await refresh_job(
                settings=worker_settings,
                http_client=http_client,
                session_maker=session_maker,
            )
            logger.info(
                "Quote worker waiting for shutdown signal",
                extra={"event": "quote_worker_waiting_for_shutdown"},
            )
            await worker_stop_event.wait()
    finally:
        if scheduler_started:
            logger.info(
                "Quote refresh scheduler shutting down",
                extra={"event": "quote_worker_scheduler_stopping"},
            )
            scheduler.shutdown(wait=False)
        logger.info(
            "Quote worker shutting down",
            extra={"event": "quote_worker_stopping"},
        )
        await engine.dispose()
