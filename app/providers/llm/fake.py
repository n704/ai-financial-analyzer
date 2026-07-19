"""Deterministic fake LLM provider (P1.4).

Selected via config like any other adapter (``llm.provider: fake``). It is the
zero-key backbone: the whole stack runs, and every test drives it without a
network. Outputs are deterministic — either scripted (for exact assertions and
recorded evals) or fabricated from the target schema (so the app just runs).

Fault injection (``error_script``) lets the contract suite exercise the typed
error path without a real provider.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from typing import Union, get_args, get_origin

from pydantic import BaseModel

from app.providers.base import (
    ContentRef,
    Message,
    NullUsageSink,
    ProviderError,
    TModel,
    UsageRecord,
    UsageSink,
)

_DEFAULT_ANSWER = "Based on the provided excerpts, this is a deterministic fake answer. [1]"


def _fabricate_value(annotation: object) -> object:
    """Best-effort deterministic value for a required field of unknown type.

    Prefers ``None`` for optionals (financial metrics are nullable by design), and
    a type-appropriate zero otherwise. Nested models recurse.
    """
    origin = get_origin(annotation)
    if origin is Union:
        args = get_args(annotation)
        if type(None) in args:
            return None
        return _fabricate_value(args[0])
    if origin in (list, Sequence, tuple):
        return []
    if origin in (dict, Mapping):
        return {}
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return _fabricate_model(annotation)
        if issubclass(annotation, bool):
            return False
        if issubclass(annotation, int):
            return 0
        if issubclass(annotation, float):
            return 0.0
        if issubclass(annotation, str):
            return "fake"
    return None


def _fabricate_model(schema: type[BaseModel]) -> BaseModel:
    """Build a valid instance filling only required-without-default fields."""
    data: dict[str, object] = {}
    for name, info in schema.model_fields.items():
        if info.is_required():
            data[info.alias or name] = _fabricate_value(info.annotation)
    return schema.model_validate(data)


class FakeLLMProvider:
    """A deterministic :class:`~app.providers.base.LLMProvider`."""

    def __init__(
        self,
        *,
        model: str = "fake-llm",
        supports_pdf_input: bool = True,
        scripted_text: Sequence[str] | None = None,
        structured: Mapping[type[BaseModel], BaseModel] | None = None,
        error_script: Sequence[ProviderError | None] | None = None,
        usage_sink: UsageSink | None = None,
    ) -> None:
        self._model = model
        self._supports_pdf = supports_pdf_input
        self._scripted = list(scripted_text) if scripted_text else []
        self._structured = dict(structured) if structured else {}
        self._errors = list(error_script) if error_script else []
        self._usage: UsageSink = usage_sink or NullUsageSink()
        self._call_index = 0

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    @property
    def supports_pdf_input(self) -> bool:
        return self._supports_pdf

    def _maybe_raise(self) -> None:
        if self._errors:
            err = self._errors.pop(0)
            if err is not None:
                raise err

    def _next_text(self) -> str:
        if not self._scripted:
            return _DEFAULT_ANSWER
        text = self._scripted[self._call_index % len(self._scripted)]
        self._call_index += 1
        return text

    def _record(self, tokens_in: int, tokens_out: int) -> None:
        self._usage.record(
            UsageRecord(
                kind="llm",
                provider="fake",
                model=self._model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )

    def generate(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        self._maybe_raise()
        text = self._next_text()
        tokens_in = sum(len(m.content.split()) for m in messages) + len(system.split())
        self._record(tokens_in, len(text.split()))
        # Stream word-by-word so callers exercise a real multi-chunk stream.
        return _stream_words(text)

    def generate_structured(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        schema: type[TModel],
        max_tokens: int | None = None,
    ) -> TModel:
        self._maybe_raise()
        tokens_in = sum(len(m.content.split()) for m in messages) + len(system.split())
        self._record(tokens_in, 0)
        override = self._structured.get(schema)
        if override is not None:
            if not isinstance(override, schema):
                raise TypeError(
                    f"scripted structured output for {schema.__name__} has wrong type "
                    f"{type(override).__name__}"
                )
            return override
        result = _fabricate_model(schema)
        assert isinstance(result, schema)
        return result

    def attach_pdf(self, *, data: bytes, display_name: str) -> ContentRef:
        if not self._supports_pdf:
            raise NotImplementedError("this fake is configured without PDF input support")
        digest = hashlib.sha256(data).hexdigest()[:16]
        return ContentRef(provider="fake", ref=f"fake-file-{digest}")


def _stream_words(text: str) -> Iterator[str]:
    words = text.split(" ")
    for i, word in enumerate(words):
        yield word if i == len(words) - 1 else word + " "
