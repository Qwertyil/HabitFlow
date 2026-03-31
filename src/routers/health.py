import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from src.database.connection import get_engine
from src.dependencies import get_redis_adapter
from src.health_checks import postgres_ready, redis_ready
from src.redis import RedisAdapter

router = APIRouter(prefix="/healthz", tags=["health"])


@router.get("/live")
async def live_health():
    return JSONResponse(content={"status": "ok"})


@router.get("/ready")
async def ready_health(
    db_engine: AsyncEngine = Depends(get_engine),
    redis: RedisAdapter = Depends(get_redis_adapter),
):
    is_postgres_ready, is_redis_ready = await asyncio.gather(
        postgres_ready(db_engine),
        redis_ready(redis),
    )
    status_code = 200 if is_postgres_ready and is_redis_ready else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if status_code == 200 else "degraded",
            "checks": {
                "postgres": "ok" if is_postgres_ready else "error",
                "redis": "ok" if is_redis_ready else "error",
            },
        },
    )
