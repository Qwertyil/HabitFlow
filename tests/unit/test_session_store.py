from __future__ import annotations

import json
from uuid import uuid4

import pytest

from src.repositories.session_store import RedisSessionStore


class _FakeRedisAdapter:
    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: int | str) -> str | None:
        return self.strings.get(str(key))

    async def set(self, key: int | str, value: object, ex: int | None = None) -> None:
        normalized_key = str(key)
        self.strings[normalized_key] = str(value)
        if ex is not None:
            self.ttls[normalized_key] = ex

    async def remove(self, key: int | str) -> None:
        normalized_key = str(key)
        self.strings.pop(normalized_key, None)
        self.sets.pop(normalized_key, None)
        self.ttls.pop(normalized_key, None)

    async def sadd(self, key: int | str, *values: str) -> int:
        normalized_key = str(key)
        target = self.sets.setdefault(normalized_key, set())
        before_size = len(target)
        target.update(str(value) for value in values)
        return len(target) - before_size

    async def srem(self, key: int | str, *values: str) -> int:
        normalized_key = str(key)
        target = self.sets.get(normalized_key, set())
        removed = 0
        for value in values:
            normalized_value = str(value)
            if normalized_value in target:
                target.remove(normalized_value)
                removed += 1
        return removed

    async def smembers(self, key: int | str) -> set[str]:
        return set(self.sets.get(str(key), set()))

    async def expire(self, key: int | str, seconds: int) -> bool:
        self.ttls[str(key)] = seconds
        return True

    async def create_session_atomically(
        self,
        *,
        session_key: str,
        serialized_payload: str,
        user_sessions_key: str,
        session_id: str,
        ttl_seconds: int,
    ) -> None:
        await self.set(session_key, serialized_payload, ex=ttl_seconds)
        await self.sadd(user_sessions_key, session_id)
        await self.expire(user_sessions_key, ttl_seconds)


@pytest.mark.asyncio
async def test_create_session_stores_payload_with_contract_keys() -> None:
    redis = _FakeRedisAdapter()
    store = RedisSessionStore(redis_adapter=redis, session_ttl_seconds=1209600)

    user_id = str(uuid4())
    session_id = "sess-abc123"
    payload = {
        "created_at": "2026-03-08T00:00:00Z",
        "expires_at": "2026-03-22T00:00:00Z",
        "ua": "pytest-agent",
        "ip": "127.0.0.1",
    }

    await store.create_session(
        session_id=session_id,
        user_id=user_id,
        payload=payload,
        ttl_seconds=600,
    )

    session_key = f"habitflow:session:{session_id}"
    index_key = f"habitflow:user:{user_id}:sessions"
    stored_payload = json.loads(redis.strings[session_key])

    assert stored_payload == {**payload, "user_id": user_id}
    assert redis.sets[index_key] == {session_id}
    assert redis.ttls[session_key] == 600
    assert redis.ttls[index_key] == 600


@pytest.mark.asyncio
async def test_create_session_uses_default_ttl_when_not_provided() -> None:
    redis = _FakeRedisAdapter()
    store = RedisSessionStore(redis_adapter=redis, session_ttl_seconds=321)

    user_id = str(uuid4())
    session_id = "sess-default-ttl"
    await store.create_session(session_id=session_id, user_id=user_id)

    assert redis.ttls[f"habitflow:session:{session_id}"] == 321
    assert redis.ttls[f"habitflow:user:{user_id}:sessions"] == 321


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl", [0, -1])
async def test_create_session_rejects_non_positive_ttl(ttl: int) -> None:
    redis = _FakeRedisAdapter()
    store = RedisSessionStore(redis_adapter=redis, session_ttl_seconds=1209600)

    with pytest.raises(ValueError, match="ttl_seconds must be greater than zero"):
        await store.create_session(
            session_id="sess-invalid-ttl",
            user_id=str(uuid4()),
            ttl_seconds=ttl,
        )


@pytest.mark.parametrize("ttl", [0, -1])
def test_init_rejects_non_positive_ttl(ttl: int) -> None:
    redis = _FakeRedisAdapter()

    with pytest.raises(
        ValueError, match="session_ttl_seconds must be greater than zero"
    ):
        RedisSessionStore(redis_adapter=redis, session_ttl_seconds=ttl)


def test_init_rejects_non_positive_ttl_explicit_zero() -> None:
    redis = _FakeRedisAdapter()

    with pytest.raises(
        ValueError, match="session_ttl_seconds must be greater than zero"
    ):
        RedisSessionStore(redis_adapter=redis, session_ttl_seconds=0)


@pytest.mark.asyncio
async def test_get_session_returns_payload_for_existing_session() -> None:
    redis = _FakeRedisAdapter()
    store = RedisSessionStore(redis_adapter=redis, session_ttl_seconds=1209600)

    session_id = "sess-get-ok"
    expected_payload = {
        "user_id": str(uuid4()),
        "created_at": "2026-03-08T00:00:00Z",
        "expires_at": "2026-03-22T00:00:00Z",
    }
    redis.strings[f"habitflow:session:{session_id}"] = json.dumps(expected_payload)

    assert await store.get_session(session_id=session_id) == expected_payload


@pytest.mark.asyncio
async def test_get_session_returns_none_for_missing_or_invalid_payload() -> None:
    redis = _FakeRedisAdapter()
    store = RedisSessionStore(redis_adapter=redis, session_ttl_seconds=1209600)

    assert await store.get_session(session_id="sess-missing") is None

    redis.strings["habitflow:session:sess-bad-json"] = "not-json"
    assert await store.get_session(session_id="sess-bad-json") is None

    redis.strings["habitflow:session:sess-not-dict"] = json.dumps(["not", "a", "dict"])
    assert await store.get_session(session_id="sess-not-dict") is None


@pytest.mark.asyncio
async def test_delete_session_removes_session_and_user_index_reference() -> None:
    redis = _FakeRedisAdapter()
    store = RedisSessionStore(redis_adapter=redis, session_ttl_seconds=1209600)

    user_id = str(uuid4())
    session_id = "sess-delete-one"
    await store.create_session(session_id=session_id, user_id=user_id)

    await store.delete_session(session_id=session_id)

    assert f"habitflow:session:{session_id}" not in redis.strings
    assert session_id not in redis.sets[f"habitflow:user:{user_id}:sessions"]


@pytest.mark.asyncio
async def test_delete_user_sessions_removes_all_user_sessions_and_index_key() -> None:
    redis = _FakeRedisAdapter()
    store = RedisSessionStore(redis_adapter=redis, session_ttl_seconds=1209600)

    user_id = str(uuid4())
    session_ids = {"sess-u-1", "sess-u-2", "sess-u-3"}
    index_key = f"habitflow:user:{user_id}:sessions"

    redis.sets[index_key] = set(session_ids)
    for session_id in session_ids:
        redis.strings[f"habitflow:session:{session_id}"] = json.dumps(
            {"user_id": user_id}
        )

    await store.delete_user_sessions(user_id=user_id)

    for session_id in session_ids:
        assert f"habitflow:session:{session_id}" not in redis.strings
    assert index_key not in redis.sets
