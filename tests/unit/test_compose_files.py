from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_compose_keeps_quote_worker_without_dev_bind_mounts() -> None:
    runtime_compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "quote-worker:" in runtime_compose
    assert 'entrypoint: ["python", "-m", "src.run_quote_worker"]' in runtime_compose
    assert "./src:/app/src" not in runtime_compose
    assert '"${POSTGRES_PORT}:5432"' not in runtime_compose
    assert '"${REDIS_PORT}:6379"' not in runtime_compose


def test_dev_compose_restores_local_bind_mounts_and_dependency_ports() -> None:
    dev_compose = (PROJECT_ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")

    assert '      - "${POSTGRES_PORT}:5432"' in dev_compose
    assert '      - "${REDIS_PORT}:6379"' in dev_compose
    assert dev_compose.count("./src:/app/src") == 2
    assert 'UVICORN_RELOAD: "true"' in dev_compose
    assert (
        'entrypoint: ["python", "-m", "watchfiles", "--filter", "python", '
        '"src.run_quote_worker:main"]' in dev_compose
    )
