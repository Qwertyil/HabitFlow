import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from src.config import settings
from src.database.connection import AsyncSessionLocal, get_engine
from src.dependencies import (
    add_quote_to_context,
    get_habit_service,
    get_redis_adapter,
    get_task_service,
)
from src.redis import RedisAdapter
from src.repositories.quote_batches import QuoteBatchRepository
from src.repositories.quotes import QuoteRepository
from src.routers.auth import router as auth_router
from src.routers.habits import router as habits_router
from src.routers.stats import router as stats_router
from src.routers.tasks import router as tasks_router
from src.routers.themes import router as themes_router
from src.services.habits import HabitService
from src.services.quotes import QuoteService
from src.services.tasks import TaskService
from src.services.zen_quote import ZenQuotesService
from src.utils import get_public_error_message, templates

logger = logging.getLogger(__name__)


logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def _build_content_security_policy(csp_nonce: str) -> str:
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' 'nonce-{csp_nonce}'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com",
            "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com",
            "img-src 'self' data: https:",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "frame-ancestors 'none'",
            "form-action 'self'",
        )
    )


async def _postgres_ready(db_engine: AsyncEngine) -> bool:
    try:
        async with db_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Readiness check failed for Postgres: %s", exc)
        return False


async def _redis_ready(redis: RedisAdapter) -> bool:
    try:
        return await redis.ping_for_healthcheck()
    except Exception as exc:
        logger.warning("Readiness check failed for Redis: %s", exc)
        return False


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient() as http_client:
        app.state.http_client = http_client

        scheduler = AsyncIOScheduler()
        app.state.scheduler = scheduler

        if getattr(settings, "TESTING", False):
            yield
            return

        scheduler.add_job(
            refresh_quotes_job,
            trigger="interval",
            hours=settings.REFILL_INTERVAL_HOURS
            if settings.REFILL_INTERVAL_HOURS
            else 12,
            kwargs={"app": app},
            id="refresh_quotes_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        scheduler.start()

        # первый запуск сразу
        await refresh_quotes_job(app)

        try:
            yield
        finally:
            scheduler.shutdown(wait=False)


app = FastAPI(
    title="HabitFlow",
    description="Трекер привычек и задач",
    version="1.0.0",
    lifespan=lifespan,
    debug=settings.DEBUG,
    docs_url="/docs" if settings.API_DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.API_DOCS_ENABLED else None,
)

app.mount("/static", StaticFiles(directory="src/static"), name="static")


app.include_router(auth_router)
app.include_router(themes_router)
app.include_router(tasks_router)
app.include_router(habits_router)
app.include_router(stats_router)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    session_cookie=settings.UI_SESSION_COOKIE_NAME,
    max_age=settings.UI_SESSION_MAX_AGE,
    same_site=settings.UI_SESSION_SAME_SITE,
    https_only=settings.UI_SESSION_HTTPS_ONLY,
)


@app.middleware("http")
async def add_security_headers(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    request.state.csp_nonce = secrets.token_urlsafe(16)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _build_content_security_policy(
        request.state.csp_nonce
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if settings.UI_SESSION_HTTPS_ONLY or settings.AUTH_SESSION_HTTPS_ONLY:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.get("/healthz/live")
async def live_health():
    return JSONResponse(content={"status": "ok"})


@app.get("/healthz/ready")
async def ready_health(
    db_engine: AsyncEngine = Depends(get_engine),
    redis: RedisAdapter = Depends(get_redis_adapter),
):
    postgres_ready, redis_ready = await asyncio.gather(
        _postgres_ready(db_engine),
        _redis_ready(redis),
    )
    status_code = 200 if postgres_ready and redis_ready else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if status_code == 200 else "degraded",
            "checks": {
                "postgres": "ok" if postgres_ready else "error",
                "redis": "ok" if redis_ready else "error",
            },
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    internal_detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    logger.info("HTTP %s: %s", exc.status_code, internal_detail)

    headers = exc.headers or {}
    redirect_location = None
    if headers:
        for header_name, header_value in headers.items():
            if header_name.lower() == "location":
                redirect_location = header_value
                break

    if redirect_location is not None and 300 <= exc.status_code < 400:
        redirect_headers = {
            header_name: header_value
            for header_name, header_value in headers.items()
            if header_name.lower() != "location"
        }
        return RedirectResponse(
            url=redirect_location,
            status_code=exc.status_code,
            headers=redirect_headers,
        )

    public_detail = get_public_error_message(exc.status_code, exc.detail)

    if "text/html" in request.headers.get("accept", ""):
        from src.utils import ensure_csrf_token

        is_login_page = request.url.path == "/auth/login"
        primary_url = "/auth/login" if is_login_page else "/"
        primary_text = "К форме входа" if is_login_page else "На главную"
        primary_icon = "fa-right-to-bracket" if is_login_page else "fa-home"

        return templates.TemplateResponse(
            request,
            "message.html",
            {
                "request": request,
                "current_user": None,
                "current_user_display_name": None,
                "title": "Ошибка",
                "message": public_detail,
                "message_type": "error",
                "primary_url": primary_url,
                "primary_text": primary_text,
                "primary_icon": primary_icon,
                "hide_sidebar": True,
                "csrf_token": ensure_csrf_token(request),
            },
            status_code=exc.status_code,
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": public_detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)

    public_detail = "Что-то пошло не так. Попробуйте ещё раз позже."

    if "text/html" in request.headers.get("accept", ""):
        from src.utils import ensure_csrf_token

        is_login_page = request.url.path == "/auth/login"
        primary_url = "/auth/login" if is_login_page else "/"
        primary_text = "К форме входа" if is_login_page else "На главную"
        primary_icon = "fa-right-to-bracket" if is_login_page else "fa-home"

        return templates.TemplateResponse(
            request,
            "message.html",
            {
                "request": request,
                "current_user": None,
                "current_user_display_name": None,
                "title": "Ошибка",
                "message": public_detail,
                "message_type": "error",
                "primary_url": primary_url,
                "primary_text": primary_text,
                "primary_icon": primary_icon,
                "hide_sidebar": True,
                "csrf_token": ensure_csrf_token(request),
            },
            status_code=500,
        )

    return JSONResponse(
        status_code=500,
        content={"detail": public_detail},
    )


@app.get("/", response_class=HTMLResponse)
async def root(
    request: Request,
    context: dict[str, Any] = Depends(add_quote_to_context),
    task_service: TaskService = Depends(get_task_service),
    habit_service: HabitService = Depends(get_habit_service),
):
    tasks, _ = await task_service.list_tasks(
        per_page=5, theme_name=request.session.get("selected_theme")
    )
    habits, _ = await habit_service.list_habits(
        per_page=4,
        theme_name=request.session.get("selected_theme"),
        due_today_only=True,
    )
    context.update({"tasks": tasks, "habits": habits, "current_page": "home"})

    return templates.TemplateResponse(request, "index.html", context)
