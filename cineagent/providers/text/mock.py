"""Offline/test TextProvider that returns scripted structured output."""
from __future__ import annotations

import json
from typing import Callable, Optional, Type

from pydantic import BaseModel

from ..base import ProviderError, T, TextProvider


class MockTextProvider(TextProvider):
    """Deterministic text provider for tests and offline pipeline runs.

    - `handler(schema) -> dict | BaseModel` lets tests script responses per schema.
    - `fail_next` injects a ProviderError to exercise error paths.
    - `malformed_next` returns non-JSON to exercise parse-failure handling.
    """

    name = "mock-text"

    def __init__(
        self,
        handler: Optional[Callable[[Type[BaseModel]], object]] = None,
        chat_text: str = "mock chat text",
    ):
        self.handler = handler
        self.chat_text = chat_text
        self.fail_next: Optional[ProviderError] = None
        self.malformed_next: bool = False
        self.last_user: str = ""

    _counter = 0

    async def chat(self, system: str, user: str, temperature: float = 0.7) -> str:
        self.last_user = user
        if self.fail_next is not None:
            err = self.fail_next
            self.fail_next = None
            raise err
        return self.chat_text

    async def structured(
        self, schema: Type[T], system: str, user: str,
        temperature: float = 0.7,
    ) -> T:
        self.last_user = user
        if self.fail_next is not None:
            err = self.fail_next
            self.fail_next = None
            raise err
        if self.malformed_next:
            self.malformed_next = False
            raise ValueError("malformed JSON (not valid JSON)")
        if self.handler is not None:
            data = self.handler(schema)
            if isinstance(data, BaseModel):
                return data  # type: ignore[return-value]
            return schema.model_validate(data)
        # default: an empty-but-valid instance of the schema
        return schema()  # type: ignore[return-value]
