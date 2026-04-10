from __future__ import annotations

import asyncio

from src.quote_worker import run_quote_worker


def main() -> None:
    asyncio.run(run_quote_worker())


if __name__ == "__main__":
    main()
