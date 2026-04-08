from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import AsyncClient
from redis.asyncio import Redis

from src.config import load_settings
from src.database.connection import get_db
from src.dependencies import require_auth
from src.redis import RedisAdapter
from src.repositories import AuthRepository, RedisSessionStore
from src.schemas.auth import AuthLogin, AuthRegister, AuthUser
from src.services.auth import LoginService, RegistrationService
from tests.helpers import async_test_client

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def protected_client(session_factory_async) -> AsyncGenerator[AsyncClient, None]:
    cfg = load_settings()
    app = FastAPI()
    app.state.settings = cfg
    app.state.redis_adapter = RedisAdapter(cfg)

    async def override_get_db(request: Request):
        async with session_factory_async() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    @app.get("/protected")
    async def protected_route(
        current_user: AuthUser = Depends(require_auth),
    ) -> dict[str, str]:
        return {"user_id": str(current_user.id)}

    try:
        async with async_test_client(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def redis_db_cleanup(redis_container) -> AsyncGenerator[None, None]:
    cfg = load_settings()
    redis_client = Redis.from_url(cfg.redis_dsn, decode_responses=True)
    await redis_client.flushdb()
    try:
        yield
    finally:
        await redis_client.flushdb()
        await redis_client.aclose()


async def test_auth_full_flow_login_resolve_logout_then_unauthorized(
    session,
    protected_client: AsyncClient,
    redis_db_cleanup,
) -> None:
    cfg = load_settings()
    auth_repo = AuthRepository(session=session)
    redis_adapter = RedisAdapter(cfg)
    session_store = RedisSessionStore(
        redis_adapter=redis_adapter,
        session_ttl_seconds=cfg.AUTH_SESSION_MAX_AGE,
    )
    registration_service = RegistrationService(
        auth_repo=auth_repo, auth_settings=cfg, session_store=session_store
    )
    login_service = LoginService(
        auth_repo=auth_repo, auth_settings=cfg, session_store=session_store
    )

    email = f"full-flow-{uuid4().hex[:12]}@example.com"
    password = "strong-pass-123"

    created_user = await registration_service.register(
        AuthRegister(email=email, password=password)
    )
    await session.commit()

    authenticated_user = await login_service.authenticate(
        AuthLogin(email=email, password=password)
    )
    assert authenticated_user is not None
    assert authenticated_user.id == created_user.id

    session_id = await login_service.create_session(user_id=authenticated_user.id)

    resolved_user = await login_service.resolve_user(session_id=session_id)
    assert resolved_user is not None
    assert resolved_user.id == authenticated_user.id

    authorized_response = await protected_client.get(
        "/protected",
        headers={"Cookie": f"{cfg.AUTH_SESSION_COOKIE_NAME}={session_id}"},
    )
    assert authorized_response.status_code == 200
    assert authorized_response.headers["content-type"].startswith("application/json")
    assert authorized_response.json()["user_id"] == str(authenticated_user.id)

    await login_service.logout(session_id=session_id, user_id=authenticated_user.id)
    assert await login_service.resolve_user(session_id=session_id) is None

    unauthorized_response = await protected_client.get(
        "/protected",
        headers={
            "Accept": "application/json",
            "Cookie": f"{cfg.AUTH_SESSION_COOKIE_NAME}={session_id}",
        },
    )
    assert unauthorized_response.status_code == 401
    assert unauthorized_response.headers["content-type"].startswith("application/json")
    assert unauthorized_response.json()["detail"] == "Authentication required"
