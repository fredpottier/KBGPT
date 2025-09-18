from __future__ import annotations

from pydantic import BaseModel


class SearchRequest(BaseModel):
    question: str
    language: str | None = None
    mime: str | None = None


__all__ = ["SearchRequest"]
