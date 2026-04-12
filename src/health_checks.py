import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.redis import RedisAdapter

logger = logging.getLogger(__name__)


async def postgres_ready(db_engine: AsyncEngine) -> bool:
    try:
        async with db_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning(
            "Postgres readiness check failed",
            extra={
                "event": "postgres_readiness_failed",
                "error": str(exc),
            },
        )
        return False


async def redis_ready(redis: RedisAdapter) -> bool:
    try:
        return await redis.ping_for_healthcheck()
    except Exception as exc:
        logger.warning(
            "Redis readiness check failed",
            extra={
                "event": "redis_readiness_failed",
                "error": str(exc),
            },
        )
        return False
