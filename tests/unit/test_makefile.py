from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_make(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_make_run_uses_selected_env_file_in_dry_run(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.test"
    env_file.write_text("APP_PORT=9123\nDEBUG=False\n", encoding="utf-8")

    result = _run_make("-n", "run", f"ENV_FILE={env_file}")

    assert result.returncode == 0
    assert (
        f"poetry run -- dotenv -f {env_file} run -- python -m src.run_app"
        in result.stdout
    )


def test_make_worker_run_uses_selected_env_file_in_dry_run(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.test"
    env_file.write_text("APP_PORT=9123\nDEBUG=False\n", encoding="utf-8")

    result = _run_make("-n", "worker-run", f"ENV_FILE={env_file}")

    assert result.returncode == 0
    assert (
        f"poetry run -- dotenv -f {env_file} run -- python -m src.run_quote_worker"
        in result.stdout
    )


def test_make_fails_fast_when_selected_env_file_is_missing(tmp_path: Path) -> None:
    missing_env_file = tmp_path / ".env.missing"

    result = _run_make("-n", "run", f"ENV_FILE={missing_env_file}")

    assert result.returncode != 0
    assert f"ENV_FILE '{missing_env_file}' does not exist" in result.stderr


def test_make_lint_does_not_require_env_file(tmp_path: Path) -> None:
    missing_env_file = tmp_path / ".env.missing"

    result = _run_make("-n", "lint", f"ENV_FILE={missing_env_file}")

    assert result.returncode == 0


def test_make_compose_up_uses_dev_override_in_dry_run(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.test"
    env_file.write_text("APP_PORT=9123\nDEBUG=False\n", encoding="utf-8")

    result = _run_make("-n", "compose-up", f"ENV_FILE={env_file}")

    assert result.returncode == 0
    assert (
        "docker compose --env-file "
        f"{env_file} -f docker-compose.yml -f docker-compose.dev.yml up -d --build"
        in result.stdout
    )


def test_make_infra_up_uses_dev_override_in_dry_run(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.test"
    env_file.write_text("APP_PORT=9123\nDEBUG=False\n", encoding="utf-8")

    result = _run_make("-n", "infra-up", f"ENV_FILE={env_file}")

    assert result.returncode == 0
    assert (
        "docker compose --env-file "
        f"{env_file} -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis"
        in result.stdout
    )


def test_make_compose_runtime_up_uses_base_compose_only_in_dry_run(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env.test"
    env_file.write_text("APP_PORT=9123\nDEBUG=False\n", encoding="utf-8")

    result = _run_make("-n", "compose-runtime-up", f"ENV_FILE={env_file}")

    assert result.returncode == 0
    assert (
        f"docker compose --env-file {env_file} -f docker-compose.yml up -d --build"
        in result.stdout
    )
    assert "docker-compose.dev.yml" not in result.stdout
