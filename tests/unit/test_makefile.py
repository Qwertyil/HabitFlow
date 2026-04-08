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


def test_make_fails_fast_when_selected_env_file_is_missing(tmp_path: Path) -> None:
    missing_env_file = tmp_path / ".env.missing"

    result = _run_make("-n", "run", f"ENV_FILE={missing_env_file}")

    assert result.returncode != 0
    assert f"ENV_FILE '{missing_env_file}' does not exist" in result.stderr


def test_make_lint_does_not_require_env_file(tmp_path: Path) -> None:
    missing_env_file = tmp_path / ".env.missing"

    result = _run_make("-n", "lint", f"ENV_FILE={missing_env_file}")

    assert result.returncode == 0
