import logging

from fastapi import FastAPI

from src.config import settings
from src.database.connection import AsyncSessionLocal
from src.repositories.quote_batches import QuoteBatchRepository
from src.repositories.quotes import QuoteRepository
from src.services.quotes import QuoteService
from src.services.zen_quote import ZenQuotesService

logger = logging.getLogger(__name__)


async def refresh_quotes_job(app: FastAPI) -> None:
    if getattr(settings, "TESTING", False):
        logger.debug("Skipping quotes refresh while running tests")
        return

    try:
        async with AsyncSessionLocal() as session:
            batch_repository = QuoteBatchRepository(session)
            quote_repository = QuoteRepository(session)
            zenquotes_service = ZenQuotesService(app.state.http_client)

            quote_service = QuoteService(
                batch_repository=batch_repository,
                quote_repository=quote_repository,
                zenquotes_service=zenquotes_service,
            )

            await quote_service.refresh_quotes_batch()
            await session.commit()

            logger.info("Quotes batch refreshed successfully")

    except Exception:
        logger.exception("Failed to refresh quotes batch")
