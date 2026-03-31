from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
import os
import socket
from typing import Any
import time
from uuid import uuid4

import docker
import psycopg2
import pytest
from fastapi import Request
from alembic import command
from alembic.config import Config
from psycopg2.extensions import connection as pg_connection
from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings
from redis import Redis as SyncRedis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from tests.helpers import async_test_client


class DatabaseConfig(BaseSettings):
    user: str = Field(alias="DATABASE_USERNAME")
    name: str = Field(alias="DATABASE_NAME")
    password: str = Field(alias="DATABASE_PASSWORD")
    port: int = Field(alias="DATABASE_PORT")
    host: str = Field(alias="DATABASE_HOST")

    @property
    def dsn(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.user,
                host=self.host,
                port=self.port,
                path=self.name,
                password=self.password,
            )
        )

    @property
    def dsn_sync(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=self.user,
                host=self.host,
                port=self.port,
                path=self.name,
                password=self.password,
            )
        )


class TestConfig:
    database = DatabaseConfig(
        DATABASE_HOST="localhost",
        DATABASE_PORT=5433,
        DATABASE_USERNAME="postgres",
        DATABASE_PASSWORD="postgres",
        DATABASE_NAME="test_template",
    )


config = TestConfig.database


def _find_free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


REDIS_TEST_PORT = _find_free_tcp_port()


SAFE_TEST_ENV = {
    "DEBUG": "true",
    "TESTING": "true",
    "CONTAINER_APP_PORT": "8000",
    "APP_PORT": "8000",
    "ZENQUOTES_API_URL": "http://test.invalid/api/random",
    "REFILL_INTERVAL_HOURS": "6",
    "UI_SESSION_SECRET_KEY": "test-ui-session-secret",
    "POSTGRES_HOST": config.host,
    "POSTGRES_PORT": str(config.port),
    "POSTGRES_USER": config.user,
    "POSTGRES_PASSWORD": config.password,
    "POSTGRES_DB": config.name,
    "REDIS_HOST": "localhost",
    "REDIS_PORT": str(REDIS_TEST_PORT),
    "REDIS_PASSWORD": "redis",
    "REDIS_DB": "0",
    "DATABASE_HOST": config.host,
    "DATABASE_PORT": str(config.port),
    "DATABASE_USERNAME": config.user,
    "DATABASE_PASSWORD": config.password,
    "DATABASE_NAME": config.name,
}


def _set_safe_test_env() -> None:
    for key, value in SAFE_TEST_ENV.items():
        os.environ[key] = value


def _reload_runtime_settings() -> None:
    from src.config import Settings, settings

    fresh_settings = Settings()
    for field_name in Settings.model_fields:
        setattr(settings, field_name, getattr(fresh_settings, field_name))

    # Drop cached values so test env changes are reflected everywhere.
    # `app.state.settings` is the same object as `settings` (see main.create_app(settings)).
    settings.__dict__.pop("session_secret_key", None)


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


_ORIGINAL_TEST_ENV = {key: os.environ.get(key) for key in SAFE_TEST_ENV}
# Применяем env до импорта тестовых модулей: часть тестов импортирует app на этапе коллекции.
_set_safe_test_env()
_reload_runtime_settings()


def _clear_auth_rate_limiters() -> None:
    from src.routers.auth import (
        login_limiters,
        oauth_callback_limiters,
        oauth_start_limiters,
        register_limiters,
    )

    limiter_groups = (
        login_limiters,
        register_limiters,
        oauth_start_limiters,
        oauth_callback_limiters,
    )

    for group in limiter_groups:
        for dependency in group:
            limiter = getattr(dependency.dependency, "limiter", None)
            bucket_factory = getattr(limiter, "bucket_factory", None)
            bucket: Any = getattr(bucket_factory, "bucket", None)
            if hasattr(bucket, "flush"):
                bucket.flush()


@pytest.fixture(scope="session", autouse=True)
def safe_test_env() -> Iterator[None]:
    _set_safe_test_env()
    _reload_runtime_settings()
    yield
    _restore_env(_ORIGINAL_TEST_ENV)


@pytest.fixture(autouse=True)
def refresh_test_runtime() -> Iterator[None]:
    _set_safe_test_env()
    _reload_runtime_settings()
    _clear_auth_rate_limiters()
    yield
    _clear_auth_rate_limiters()


def get_db_connection(dbname=None) -> pg_connection:
    """Создает подключение к тестовой БД"""
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=dbname or config.name,  # Если dbname не указан, используем config.name
    )


@pytest.fixture(scope="session")
def postgres_container():
    container_name = f"test_postgres_{uuid4().hex[:8]}"
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:
        pytest.skip(f"Docker is required for integration tests: {exc}")

    try:
        client.containers.run(
            image="postgres:17-alpine",
            name=container_name,
            environment={
                "POSTGRES_USER": config.user,
                "POSTGRES_PASSWORD": config.password,
                "POSTGRES_DB": config.name,
            },
            ports={"5432/tcp": config.port},
            detach=True,
            remove=True,
        )

        for _ in range(30):  # 30 попыток по 0.5 сек = 15 сек
            try:
                conn = get_db_connection()
                conn.close()
                break
            except psycopg2.OperationalError:
                time.sleep(0.5)
        else:
            raise Exception("PostgreSQL container failed to start")

        yield container_name

    finally:
        try:
            cont = client.containers.get(container_name)
            cont.stop(timeout=1)
        except docker.errors.NotFound:
            pass


@pytest.fixture(scope="session")
def redis_container():
    container_name = f"test_redis_{uuid4().hex[:8]}"
    redis_client: SyncRedis | None = None
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:
        pytest.skip(f"Docker is required for integration tests: {exc}")

    try:
        client.containers.run(
            image="redis:7-alpine",
            name=container_name,
            command=[
                "redis-server",
                "--appendonly",
                "no",
                "--requirepass",
                SAFE_TEST_ENV["REDIS_PASSWORD"],
            ],
            ports={"6379/tcp": int(SAFE_TEST_ENV["REDIS_PORT"])},
            detach=True,
            remove=True,
        )

        redis_client = SyncRedis(
            host=SAFE_TEST_ENV["REDIS_HOST"],
            port=int(SAFE_TEST_ENV["REDIS_PORT"]),
            password=SAFE_TEST_ENV["REDIS_PASSWORD"],
            db=int(SAFE_TEST_ENV["REDIS_DB"]),
            decode_responses=True,
            socket_connect_timeout=1,
        )
        for _ in range(30):  # 30 попыток по 0.5 сек = 15 сек
            try:
                if redis_client.ping():
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise Exception("Redis container failed to start")

        yield container_name

    finally:
        if redis_client is not None:
            redis_client.close()
        try:
            cont = client.containers.get(container_name)
            cont.stop(timeout=1)
        except docker.errors.NotFound:
            pass


@pytest.fixture(scope="session")
def template_db(postgres_container):
    """Создает шаблонную БД с примененными миграциями"""
    # Создаем шаблонную БД
    conn = get_db_connection(dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()

    # Удаляем шаблонную БД, если она уже существует (на случай перезапуска)
    cur.execute(f"DROP DATABASE IF EXISTS {config.name};")
    cur.execute(f"CREATE DATABASE {config.name};")
    cur.close()
    conn.close()

    # Применяем миграции к шаблонной БД
    run_alembic_migrations()
    conn = get_db_connection(dbname=config.name)
    cur = conn.cursor()
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public';")
    cur.fetchall()
    conn.close()

    # Запрещаем подключения к шаблонной БД (требование для использования в качестве шаблона)
    conn = get_db_connection(dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"ALTER DATABASE {config.name} ALLOW_CONNECTIONS false;")
    cur.close()
    conn.close()


def run_alembic_migrations():
    """Применяет миграции Alembic синхронно к тестовой БД"""
    dsn = f"postgresql://{config.user}:{config.password}@{config.host}:{config.port}/{config.name}"
    os.environ["TESTING"] = "true"

    current_dir = os.path.dirname(os.path.abspath(__file__))
    base_path = os.path.dirname(current_dir)
    migrations_path = os.path.join(base_path, "src", "database", "migrations")

    # Создаём конфиг без файла alembic.ini
    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", migrations_path)
    alembic_cfg.set_main_option("sqlalchemy.url", dsn)

    # Применяем миграции до головной версии
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="function")
def test_db(template_db):
    """Создает временную БД как клон шаблона и возвращает DSN"""
    tmp_name = f"test_{uuid4().hex}"

    # Подключаемся к системной БД для создания новой БД из шаблона
    conn = get_db_connection(dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()

    # Клонируем шаблон
    cur.execute(f"CREATE DATABASE {tmp_name} TEMPLATE {config.name};")
    cur.close()
    conn.close()

    # Возвращаем DSN для асинхронного подключения (используем asyncpg)
    dsn = f"postgresql+asyncpg://{config.user}:{config.password}@{config.host}:{config.port}/{tmp_name}"
    yield dsn

    # После теста удаляем временную БД
    conn = get_db_connection(dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()

    # Принудительно завершаем все соединения к временной БД
    cur.execute(f"""
        SELECT pg_terminate_backend(pg_stat_activity.pid)
        FROM pg_stat_activity
        WHERE pg_stat_activity.datname = '{tmp_name}'
        AND pid <> pg_backend_pid();
    """)
    cur.execute(f"DROP DATABASE {tmp_name};")
    cur.close()
    conn.close()


@pytest.fixture
async def engine_async(test_db):
    """Создает async-движок для временной тестовой БД"""
    engine = create_async_engine(test_db)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory_async(engine_async) -> sessionmaker:
    """Фабрика для создания async-сессий"""
    return sessionmaker(engine_async, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(session_factory_async):
    """Асинхронная сессия для работы с БД"""
    async with session_factory_async() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def redis_db_cleanup(redis_container) -> AsyncGenerator[None, None]:
    from redis.asyncio import Redis
    from src.config import settings

    redis_client = Redis.from_url(settings.redis_dsn, decode_responses=True)
    await redis_client.flushdb()
    try:
        yield
    finally:
        await redis_client.flushdb()
        await redis_client.aclose()


@pytest.fixture
async def authenticated_user(session, redis_db_cleanup):
    from src.repositories import AuthRepository

    auth_repo = AuthRepository(session=session)
    user = await auth_repo.create_user(
        email=f"test-{uuid4().hex[:12]}@example.com",
        password_hash=None,
    )
    await session.commit()
    return user


@pytest.fixture
def owner_id(authenticated_user):
    return authenticated_user.id


@pytest.fixture
async def secondary_authenticated_user(session, redis_db_cleanup):
    from src.repositories import AuthRepository

    auth_repo = AuthRepository(session=session)
    user = await auth_repo.create_user(
        email=f"test-{uuid4().hex[:12]}@example.com",
        password_hash=None,
    )
    await session.commit()
    return user


@pytest.fixture
def secondary_owner_id(secondary_authenticated_user):
    return secondary_authenticated_user.id


@pytest.fixture
async def auth_session_id(session, authenticated_user, redis_db_cleanup) -> str:
    from src.config import settings
    from src.redis import RedisAdapter
    from src.repositories import AuthRepository, RedisSessionStore
    from src.services.auth import LoginService

    redis_adapter = RedisAdapter(settings)
    login_service = LoginService(
        auth_repo=AuthRepository(session=session),
        session_store=RedisSessionStore(
            redis_adapter=redis_adapter,
            session_ttl_seconds=settings.AUTH_SESSION_MAX_AGE,
        ),
    )
    session_id = await login_service.create_session(authenticated_user.id)
    await session.commit()
    return session_id


@pytest.fixture
async def secondary_auth_session_id(
    session, secondary_authenticated_user, redis_db_cleanup
) -> str:
    from src.config import settings
    from src.redis import RedisAdapter
    from src.repositories import AuthRepository, RedisSessionStore
    from src.services.auth import LoginService

    redis_adapter = RedisAdapter(settings)
    login_service = LoginService(
        auth_repo=AuthRepository(session=session),
        session_store=RedisSessionStore(
            redis_adapter=redis_adapter,
            session_ttl_seconds=settings.AUTH_SESSION_MAX_AGE,
        ),
    )
    session_id = await login_service.create_session(secondary_authenticated_user.id)
    await session.commit()
    return session_id


@pytest.fixture
def authed_client_factory(engine_async, session_factory_async):
    """
    Фабрика авторизованных FastAPI-клиентов с переопределённой зависимостью БД.
    """
    from src.database.connection import get_db
    from src.database.connection import get_engine
    from src.config import settings
    from src.main import app

    @asynccontextmanager
    async def make_client(session_id: str):
        async def override_get_db(request: Request):
            async with session_factory_async() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_engine] = lambda: engine_async

        async with async_test_client(app) as client:
            client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, session_id)
            yield client

        app.dependency_overrides.clear()

    return make_client


@pytest.fixture
async def client(authed_client_factory, auth_session_id):
    async with authed_client_factory(auth_session_id) as client:
        yield client


@pytest.fixture
async def secondary_client(authed_client_factory, secondary_auth_session_id):
    async with authed_client_factory(secondary_auth_session_id) as client:
        yield client
