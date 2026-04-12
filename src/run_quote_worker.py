from __future__ import annotations

import asyncio

from src.config import load_settings
from src.logging_config import configure_logging
from src.quote_worker import run_quote_worker


def main() -> None:
    settings = load_settings()
    configure_logging(settings, component="worker")

    asyncio.run(run_quote_worker(settings))


if __name__ == "__main__":
    main()
