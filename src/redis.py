from __future__ import annotations

import asyncio
import builtins
import inspect
import logging
from types import TracebackType
from typing import Any, Self, cast

from redis.asyncio import Redis
from redis.exceptions import ConnectionError, RedisError

from src.config import Settings

logger = logging.getLogger(__name__)

_DEFAULT_SOCKET_TIMEOUT_SECONDS = 5
_HEALTHCHECK_SOCKET_TIMEOUT_SECONDS = 1


class RedisAdapter:
    def __init__(self, settings: Settings) -> None:
        self.dsn = settings.redis_dsn
        self._redis: Redis | None = None  # указываем тип
        self._retry_attempts = 3
        self._retry_delay = 1

    def _build_client(
        self,
        *,
        socket_connect_timeout: int,
        socket_timeout: int,
        retry_on_timeout: bool,
    ) -> Redis:
        return Redis.from_url(
            self.dsn,
            decode_responses=True,
            socket_connect_timeout=socket_connect_timeout,
            socket_keepalive=True,
            retry_on_timeout=retry_on_timeout,
            socket_timeout=socket_timeout,
        )

    async def _get_connection(self) -> Redis:
        for attempt in range(self._retry_attempts):
            try:
                if self._redis is None:
                    self._redis = self._build_client(
                        socket_connect_timeout=_DEFAULT_SOCKET_TIMEOUT_SECONDS,
                        socket_timeout=_DEFAULT_SOCKET_TIMEOUT_SECONDS,
                        retry_on_timeout=True,
                    )

                # после проверки self._redis точно не None
                assert self._redis is not None
                if not await self._redis.ping():  # type: ignore[misc]
                    await self._redis.aclose()
                    self._redis = None
                    raise ConnectionError("Redis connection failed")
                return self._redis
            except (RedisError, ConnectionError) as e:
                if attempt == self._retry_attempts - 1:
                    logger.error(
                        "Redis connection retries exhausted",
                        extra={
                            "event": "redis_connection_retries_exhausted",
                            "attempts": self._retry_attempts,
                        },
                    )
                    raise
                logger.warning(
                    "Redis connection attempt failed",
                    extra={
                        "event": "redis_connection_retry",
                        "attempt": attempt + 1,
                        "attempts": self._retry_attempts,
                        "error": str(e),
                    },
                )
                await asyncio.sleep(self._retry_delay)
        raise RuntimeError("Unexpected end of connection attempts")

    async def _execute_with_retry(
        self, cmd: str, *args: object, **kwargs: object
    ) -> Any:
        for attempt in range(self._retry_attempts):
            try:
                redis = await self._get_connection()
                method = getattr(redis, cmd)
                return await method(*args, **kwargs)
            except (ConnectionError, TimeoutError):
                if attempt == self._retry_attempts - 1:
                    raise
                await asyncio.sleep(self._retry_delay)
        raise RuntimeError("Unexpected end of retry loop")

    async def get(self, key: int | str) -> Any:
        return await self._execute_with_retry("get", str(key))

    async def ping(self) -> bool:
        return bool(await self._execute_with_retry("ping"))

    async def ping_for_healthcheck(self) -> bool:
        redis = self._build_client(
            socket_connect_timeout=_HEALTHCHECK_SOCKET_TIMEOUT_SECONDS,
            socket_timeout=_HEALTHCHECK_SOCKET_TIMEOUT_SECONDS,
            retry_on_timeout=False,
        )
        try:
            ping_result = redis.ping()
            if inspect.isawaitable(ping_result):
                ping_result = await ping_result
            return bool(ping_result)
        finally:
            await redis.aclose()

    async def set(self, key: int | str, value: Any, ex: int | None = None) -> None:
        if ex is not None:
            await self._execute_with_retry("set", str(key), value, ex=ex)
        else:
            await self._execute_with_retry("set", str(key), value)

    async def remove(self, key: int | str) -> None:
        await self._execute_with_retry("delete", str(key))

    async def sadd(self, key: int | str, *values: str) -> int:
        if not values:
            return 0
        result = await self._execute_with_retry(
            "sadd", str(key), *(str(value) for value in values)
        )
        return int(result)

    async def srem(self, key: int | str, *values: str) -> int:
        if not values:
            return 0
        result = await self._execute_with_retry(
            "srem", str(key), *(str(value) for value in values)
        )
        return int(result)

    async def smembers(self, key: int | str) -> builtins.set[str]:
        result = await self._execute_with_retry("smembers", str(key))
        return cast(builtins.set[str], result)

    async def expire(self, key: int | str, seconds: int) -> bool:
        return bool(await self._execute_with_retry("expire", str(key), seconds))

    async def exists(self, key: int | str) -> bool:
        return bool(await self._execute_with_retry("exists", str(key)))

    async def keys(self, pattern: str = "*") -> list[str]:
        result = await self._execute_with_retry("keys", pattern)
        return cast(list[str], result)

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as e:
                logger.warning(
                    "Redis connection close failed",
                    extra={
                        "event": "redis_close_failed",
                        "error": str(e),
                    },
                )
            finally:
                self._redis = None

    async def create_session_atomically(
        self,
        *,
        session_key: str,
        serialized_payload: str,
        user_sessions_key: str,
        session_id: str,
        ttl_seconds: int,
    ) -> None:
        redis = await self._get_connection()
        async with redis.pipeline(transaction=True) as pipe:
            pipe.set(session_key, serialized_payload, ex=ttl_seconds)
            pipe.sadd(user_sessions_key, session_id)
            pipe.expire(user_sessions_key, ttl_seconds)
            await pipe.execute()

    async def __aenter__(self) -> Self:
        await self._get_connection()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
