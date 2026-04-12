from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from src.config import Settings, load_settings
from src.exception_handlers import register_exception_handlers
from src.lifespan import lifespan
from src.middleware.request_context import register_request_context_middleware
from src.middleware.security_headers import register_security_headers_middleware
from src.routers.auth import router as auth_router
from src.routers.habits import router as habits_router
from src.routers.health import router as health_router
from src.routers.home import router as home_router
from src.routers.stats import router as stats_router
from src.routers.tasks import router as tasks_router
from src.routers.themes import router as themes_router


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings if settings is not None else load_settings()
    app = FastAPI(
        title="HabitFlow",
        description="Трекер привычек и задач",
        version="1.0.0",
        lifespan=lifespan,
        debug=app_settings.DEBUG,
        docs_url="/docs" if app_settings.API_DOCS_ENABLED else None,
        redoc_url="/redoc" if app_settings.API_DOCS_ENABLED else None,
        openapi_url="/openapi.json" if app_settings.API_DOCS_ENABLED else None,
    )
    app.state.settings = app_settings

    app.mount("/static", StaticFiles(directory="src/static"), name="static")

    app.include_router(auth_router)
    app.include_router(themes_router)
    app.include_router(tasks_router)
    app.include_router(habits_router)
    app.include_router(stats_router)
    app.include_router(health_router)
    app.include_router(home_router)

    app.add_middleware(
        SessionMiddleware,
        secret_key=app_settings.session_secret_key,
        session_cookie=app_settings.UI_SESSION_COOKIE_NAME,
        max_age=app_settings.UI_SESSION_MAX_AGE,
        same_site=app_settings.UI_SESSION_SAME_SITE,
        https_only=app_settings.UI_SESSION_HTTPS_ONLY,
    )
    register_security_headers_middleware(app)
    register_exception_handlers(app)
    register_request_context_middleware(app)

    return app
