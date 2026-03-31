import logging

import httpx
from annotated_types import MaxLen
from pydantic import BaseModel, ValidationError

from src.schemas import QuoteCreate, ZenquoteAPI

logger = logging.getLogger(__name__)


def get_max_length(model: type[BaseModel], field_name: str) -> int | None:
    field = model.model_fields[field_name]
    for meta in field.metadata:
        if isinstance(meta, MaxLen):
            return meta.max_length
    return None


max_text_len = get_max_length(QuoteCreate, "text")
max_author_len = get_max_length(QuoteCreate, "author")


class ZenQuotesService:
    def __init__(self, http_client: httpx.AsyncClient, *, api_url: str):
        self._http_client = http_client
        self._api_url = api_url

    async def fetch_batch(self) -> list[ZenquoteAPI]:
        try:
            response = await self._http_client.get(
                self._api_url,
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("ZenQuotes returned 429 Too Many Requests")
                return []
            raise
        except httpx.RequestError as e:
            logger.warning("ZenQuotes request failed: %s", e)
            return []

        try:
            payload = response.json()
        except ValueError:
            logger.warning("ZenQuotes returned invalid JSON")
            return []

        quotes_list: list[ZenquoteAPI] = []

        for item in payload:
            try:
                zenquote = ZenquoteAPI.model_validate(item)
            except ValidationError:
                logger.debug("Skipping invalid quote payload: %r", item)
                continue

            if max_text_len is not None and len(zenquote.text) > max_text_len:
                continue

            if (
                zenquote.author is not None
                and max_author_len is not None
                and len(zenquote.author) > max_author_len
            ):
                continue

            quotes_list.append(zenquote)

        return quotes_list
