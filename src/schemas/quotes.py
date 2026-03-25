from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.database.models.quotes import TaskStatus

from .base import InDBBase


class QuoteBatch(BaseModel):
    source: str = Field(max_length=128)
    status: TaskStatus


class QuoteBatchInDB(QuoteBatch, InDBBase):
    pass


class QuoteBatchUpdate(BaseModel):
    source: str | None = Field(default=None, max_length=128)
    status: TaskStatus | None = None


class ZenquoteAPI(BaseModel):
    text: str = Field(alias="q")
    author: str | None = Field(alias="a")
    id: int = Field(alias="c")
    html: str = Field(alias="h")


class QuoteCreate(BaseModel):
    batch_id: UUID
    text: str = Field(max_length=256)
    author: str = Field(max_length=128)


class QuoteInDB(QuoteCreate, InDBBase):
    pass


class QuoteUpdate(BaseModel):
    text: str | None = Field(default=None, max_length=256)
    author: str | None = Field(default=None, max_length=128)


class QuoteAnswer(BaseModel):
    text: str
    author: str

    model_config = ConfigDict(from_attributes=True)
