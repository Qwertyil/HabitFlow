import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from src.redis import RedisAdapter


class RedisSessionStore:
    _SESSION_KEY_PREFIX = "habitflow:session:"
    _USER_SESSIONS_KEY_PREFIX = "habitflow:user:"

    def __init__(
        self,
        redis_adapter: RedisAdapter,
        *,
        session_ttl_seconds: int,
    ) -> None:
        self._redis = redis_adapter
        if session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be greater than zero")
        self._session_ttl_seconds = session_ttl_seconds

    @classmethod
    def _session_key(cls, session_id: str) -> str:
        return f"{cls._SESSION_KEY_PREFIX}{session_id}"

    @classmethod
    def _user_sessions_key(cls, user_id: str | UUID) -> str:
        return f"{cls._USER_SESSIONS_KEY_PREFIX}{user_id}:sessions"

    async def create_session(
        self,
        session_id: str,
        user_id: str | UUID,
        payload: Mapping[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._session_ttl_seconds
        if ttl <= 0:
            raise ValueError("ttl_seconds must be greater than zero")

        normalized_user_id = str(user_id)
        session_payload = dict(payload or {})
        session_payload["user_id"] = normalized_user_id

        session_key = self._session_key(session_id)
        user_sessions_key = self._user_sessions_key(normalized_user_id)
        serialized_payload = json.dumps(
            session_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

        await self._redis.create_session_atomically(
            session_key=session_key,
            serialized_payload=serialized_payload,
            user_sessions_key=user_sessions_key,
            session_id=session_id,
            ttl_seconds=ttl,
        )

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        raw_payload = await self._redis.get(self._session_key(session_id))
        if raw_payload is None or not isinstance(raw_payload, str):
            return None

        try:
            decoded_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            return None

        if not isinstance(decoded_payload, dict):
            return None
        return decoded_payload

    async def delete_session(self, session_id: str) -> None:
        session_payload = await self.get_session(session_id)
        await self._redis.remove(self._session_key(session_id))

        if session_payload is None:
            return

        user_id = session_payload.get("user_id")
        if user_id is None:
            return

        await self._redis.srem(self._user_sessions_key(str(user_id)), session_id)

    async def delete_user_sessions(self, user_id: str | UUID) -> None:
        user_sessions_key = self._user_sessions_key(user_id)
        session_ids = await self._redis.smembers(user_sessions_key)

        for session_id in session_ids:
            await self._redis.remove(self._session_key(session_id))

        await self._redis.remove(user_sessions_key)
