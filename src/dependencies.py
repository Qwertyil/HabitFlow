from typing import Annotated, Any, cast
from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.database.connection import get_db
from src.redis import RedisAdapter
from src.repositories import (
    AuthRepository,
    HabitRepository,
    RedisSessionStore,
    TaskRepository,
    ThemeRepository,
)
from src.repositories.quote_batches import QuoteBatchRepository
from src.repositories.quotes import QuoteRepository
from src.schemas import Stats
from src.schemas.auth import AuthUser
from src.services import HabitService, StatisticsService, TaskService, ThemeService
from src.services.auth import LoginService, OAuthService, RegistrationService
from src.services.quotes import QuoteService
from src.services.zen_quote import ZenQuotesService
from src.utils import build_template_context

_AUTH_LOGIN_PATH = "/auth/login"


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _is_html_request(request: Request) -> bool:
    accept = request.headers.get("accept", "").lower()
    content_type = request.headers.get("content-type", "").lower()

    if "text/html" in accept:
        return True
    return any(
        expected_content_type in content_type
        for expected_content_type in (
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        )
    )


def _login_redirect_target(request: Request) -> str:
    original_target = request.url.path
    if request.url.query:
        original_target = f"{original_target}?{request.url.query}"
    return f"{_AUTH_LOGIN_PATH}?next={quote(original_target, safe='')}"


def get_redis_adapter(request: Request) -> RedisAdapter:
    return cast(RedisAdapter, request.app.state.redis_adapter)


async def get_auth_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthRepository:
    """Провайдер для auth-репозитория."""
    return AuthRepository(session=db)


async def get_session_store(
    redis_adapter: RedisAdapter = Depends(get_redis_adapter),
    app_settings: Settings = Depends(get_settings),
) -> RedisSessionStore:
    """Провайдер для session-store (Redis)."""
    return RedisSessionStore(
        redis_adapter=redis_adapter,
        session_ttl_seconds=app_settings.AUTH_SESSION_MAX_AGE,
    )


async def get_http_client(request: Request) -> httpx.AsyncClient | None:
    http_client = getattr(request.app.state, "http_client", None)
    return http_client if isinstance(http_client, httpx.AsyncClient) else None


async def get_login_service(
    auth_repo: AuthRepository = Depends(get_auth_repository),
    session_store: RedisSessionStore = Depends(get_session_store),
    http_client: httpx.AsyncClient | None = Depends(get_http_client),
    auth_settings: Settings = Depends(get_settings),
) -> LoginService:
    """Провайдер для LoginService."""
    return LoginService(
        auth_repo=auth_repo,
        auth_settings=auth_settings,
        session_store=session_store,
        http_client=http_client,
    )


async def get_registration_service(
    auth_repo: AuthRepository = Depends(get_auth_repository),
    session_store: RedisSessionStore = Depends(get_session_store),
    http_client: httpx.AsyncClient | None = Depends(get_http_client),
    auth_settings: Settings = Depends(get_settings),
) -> RegistrationService:
    """Провайдер для RegistrationService."""
    return RegistrationService(
        auth_repo=auth_repo,
        auth_settings=auth_settings,
        session_store=session_store,
        http_client=http_client,
    )


async def get_oauth_service(
    auth_repo: AuthRepository = Depends(get_auth_repository),
    session_store: RedisSessionStore = Depends(get_session_store),
    http_client: httpx.AsyncClient | None = Depends(get_http_client),
    auth_settings: Settings = Depends(get_settings),
) -> OAuthService:
    """Провайдер для OAuthService."""
    return OAuthService(
        auth_repo=auth_repo,
        auth_settings=auth_settings,
        session_store=session_store,
        http_client=http_client,
    )


async def get_current_user(
    request: Request,
    login_service: LoginService = Depends(get_login_service),
    auth_settings: Settings = Depends(get_settings),
) -> AuthUser | None:
    """Достать пользователя по session-id из cookie через Redis и БД."""
    session_id = request.cookies.get(auth_settings.AUTH_SESSION_COOKIE_NAME)
    if not session_id:
        return None

    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        return None

    return await login_service.resolve_user(session_id=normalized_session_id)


async def optional_user(
    current_user: AuthUser | None = Depends(get_current_user),
) -> AuthUser | None:
    """Опциональный пользователь: `None`, если не авторизован."""
    return current_user


async def require_auth(
    request: Request,
    current_user: AuthUser | None = Depends(get_current_user),
) -> AuthUser:
    """Требует авторизацию; для HTML делает redirect, иначе отдаёт 401 JSON."""
    if current_user is not None:
        return current_user

    if _is_html_request(request):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Authentication required",
            headers={"Location": _login_redirect_target(request)},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


async def get_theme_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: AuthUser | None = Depends(get_current_user),
) -> ThemeRepository:
    """Провайдер для репозитория тем"""
    return ThemeRepository(
        session=db,
        owner_id=current_user.id if current_user is not None else None,
    )


async def get_user_theme_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: AuthUser = Depends(require_auth),
) -> ThemeRepository:
    """Провайдер для репозитория тем с обязательной авторизацией."""
    return ThemeRepository(session=db, owner_id=current_user.id)


async def get_theme_service(
    theme_repo: ThemeRepository = Depends(get_theme_repository),
) -> ThemeService:
    """Провайдер для сервиса тем"""
    return ThemeService(theme_repo=theme_repo)


async def get_user_theme_service(
    theme_repo: ThemeRepository = Depends(get_user_theme_repository),
) -> ThemeService:
    """Провайдер для сервиса тем с обязательной авторизацией."""
    return ThemeService(theme_repo=theme_repo)


async def get_task_repository(
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser | None = Depends(get_current_user),
) -> TaskRepository:
    return TaskRepository(
        session=db,
        owner_id=current_user.id if current_user is not None else None,
    )


async def get_user_task_repository(
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(require_auth),
) -> TaskRepository:
    """Провайдер для репозитория задач с обязательной авторизацией."""
    return TaskRepository(session=db, owner_id=current_user.id)


async def get_task_service(
    task_repo: TaskRepository = Depends(get_task_repository),
    theme_repo: ThemeRepository = Depends(get_theme_repository),
) -> TaskService:
    """Провайдер для сервиса задач"""
    return TaskService(task_repo=task_repo, theme_repo=theme_repo)


async def get_user_task_service(
    task_repo: TaskRepository = Depends(get_user_task_repository),
    theme_repo: ThemeRepository = Depends(get_user_theme_repository),
) -> TaskService:
    """Провайдер для сервиса задач с обязательной авторизацией."""
    return TaskService(task_repo=task_repo, theme_repo=theme_repo)


async def get_habit_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: AuthUser | None = Depends(get_current_user),
) -> HabitRepository:
    """Провайдер для репозитория привычек"""
    return HabitRepository(
        session=db,
        owner_id=current_user.id if current_user is not None else None,
    )


async def get_user_habit_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: AuthUser = Depends(require_auth),
) -> HabitRepository:
    """Провайдер для репозитория привычек с обязательной авторизацией."""
    return HabitRepository(session=db, owner_id=current_user.id)


async def get_habit_service(
    habit_repo: HabitRepository = Depends(get_habit_repository),
    theme_repo: ThemeRepository = Depends(get_theme_repository),
) -> HabitService:
    """Провайдер для сервиса привычек"""
    return HabitService(habit_repo=habit_repo, theme_repo=theme_repo)


async def get_user_habit_service(
    habit_repo: HabitRepository = Depends(get_user_habit_repository),
    theme_repo: ThemeRepository = Depends(get_user_theme_repository),
) -> HabitService:
    """Провайдер для сервиса привычек с обязательной авторизацией."""
    return HabitService(habit_repo=habit_repo, theme_repo=theme_repo)


async def get_statistics_service(
    task_service: TaskService = Depends(get_task_service),
    habit_service: HabitService = Depends(get_habit_service),
    theme_service: ThemeService = Depends(get_theme_service),
) -> StatisticsService:
    """Провайдер для page-level статистики `/stats`."""
    return StatisticsService(
        task_service=task_service,
        habit_service=habit_service,
        theme_service=theme_service,
    )


async def get_stats(
    task_service: TaskService = Depends(get_task_service),
    habits_service: HabitService = Depends(get_habit_service),
) -> Stats:
    task_statistics = await task_service.get_task_statistics()
    habit_statistics = await habits_service.get_habit_statistics()
    return Stats(
        total_tasks=task_statistics.total,
        active_tasks=task_statistics.pending,
        total_habits=habit_statistics.total,
        success_rate=habit_statistics.success_rate,
        active_habits=habit_statistics.active,
        due_habits_today=habit_statistics.due_today,
        completed_habits_today=habit_statistics.completed_today,
    )


async def get_template_context(
    request: Request,
    theme_service: ThemeService = Depends(get_theme_service),
    statistics: Stats = Depends(get_stats),
    current_user: Annotated[AuthUser | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    return await build_template_context(
        request,
        theme_service=theme_service,
        statistics=statistics,
        current_user=current_user,
    )


def get_quote_repository(
    session: AsyncSession = Depends(get_db),
) -> QuoteRepository:
    return QuoteRepository(session)


def get_quote_batch_repository(
    session: AsyncSession = Depends(get_db),
) -> QuoteBatchRepository:
    return QuoteBatchRepository(session)


def get_zenquotes_service(
    http_client: httpx.AsyncClient | None = Depends(get_http_client),
    app_settings: Settings = Depends(get_settings),
) -> ZenQuotesService:
    if http_client is None:
        raise RuntimeError("HTTP client is not available")
    return ZenQuotesService(
        http_client,
        api_url=app_settings.ZENQUOTES_API_URL,
    )


def get_quote_service(
    quote_repository: QuoteRepository = Depends(get_quote_repository),
    batch_repository: QuoteBatchRepository = Depends(get_quote_batch_repository),
    zenquotes_service: ZenQuotesService = Depends(get_zenquotes_service),
) -> QuoteService:
    return QuoteService(
        batch_repository=batch_repository,
        quote_repository=quote_repository,
        zenquotes_service=zenquotes_service,
    )


async def add_quote_to_context(
    context: dict[str, Any] = Depends(get_template_context),
    quote_service: QuoteService = Depends(get_quote_service),
) -> dict[str, Any]:
    context["quote"] = await quote_service.get_random_quote()
    return context
