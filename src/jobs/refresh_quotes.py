import logging

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import Settings
from src.repositories.quote_batches import QuoteBatchRepository
from src.repositories.quotes import QuoteRepository
from src.services.quotes import QuoteService
from src.services.zen_quote import ZenQuotesService

logger = logging.getLogger(__name__)


def build_quote_service(
    *,
    session: AsyncSession,
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> QuoteService:
    batch_repository = QuoteBatchRepository(session)
    quote_repository = QuoteRepository(session)
    zenquotes_service = ZenQuotesService(
        http_client,
        api_url=settings.ZENQUOTES_API_URL,
    )
    return QuoteService(
        batch_repository=batch_repository,
        quote_repository=quote_repository,
        zenquotes_service=zenquotes_service,
    )


async def refresh_quotes(
    *,
    settings: Settings,
    http_client: httpx.AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    if settings.TESTING:
        logger.debug("Skipping quotes refresh while running tests")
        return

    try:
        async with session_maker() as session:
            quote_service = build_quote_service(
                session=session,
                http_client=http_client,
                settings=settings,
            )
            await quote_service.refresh_quotes_batch()
            await session.commit()

            logger.info("Quotes batch refreshed successfully")

    except Exception:
        logger.exception("Failed to refresh quotes batch")


async def refresh_quotes_job(app: FastAPI) -> None:
    await refresh_quotes(
        settings=app.state.settings,
        http_client=app.state.http_client,
        session_maker=app.state.async_session_maker,
    )
