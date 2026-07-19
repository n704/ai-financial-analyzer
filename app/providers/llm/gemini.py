"""Gemini LLM adapter (P1.5) — the default, free-tier LLM.

Wraps ``google-genai`` behind :class:`~app.providers.base.LLMProvider`. Everything
provider-specific lives here: SDK calls, streaming, ``response_schema``-based
structured output (+ one validation retry), the Files API for native-PDF
attachment, 429-aware backoff, and usage reporting. Core code never imports this
module directly — it goes through the factory (P1.3) and the ``LLMProvider``
protocol.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence

from google.genai import Client, types
from pydantic import ValidationError

from app.providers._gemini_errors import gemini_retry_hint, to_provider_error
from app.providers.base import (
    ContentRef,
    Message,
    NullUsageSink,
    ProviderInvalidResponse,
    ProviderRefusal,
    ProviderUnavailable,
    TModel,
    UsageRecord,
    UsageSink,
)
from app.providers.retry import with_backoff

_REFUSAL_REASONS = {
    types.FinishReason.SAFETY,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.SPII,
    types.FinishReason.RECITATION,
}


def _role_for(message: Message) -> str:
    # Gemini's chat vocabulary is "user" / "model"; ours is "user" / "assistant".
    return "model" if message.role == "assistant" else "user"


def _parts_for(message: Message) -> list[types.Part]:
    parts: list[types.Part] = [types.Part.from_text(text=message.content)]
    for ref in message.attachments:
        if ref.provider != "gemini":
            continue  # a file ref minted by a different provider is never replayed
        parts.append(types.Part.from_uri(file_uri=ref.ref, mime_type=ref.mime_type))
    return parts


def _contents_for(messages: Sequence[Message]) -> list[types.Content]:
    return [types.Content(role=_role_for(m), parts=_parts_for(m)) for m in messages]


class GeminiLLMProvider:
    """Gemini implementation of :class:`~app.providers.base.LLMProvider`."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        options: dict[str, object] | None = None,
        usage_sink: UsageSink | None = None,
        max_retries: int = 5,
    ) -> None:
        self._model = model
        self._options = dict(options or {})
        self._usage: UsageSink = usage_sink or NullUsageSink()
        self._max_retries = max_retries
        self._client = Client(api_key=api_key)

    @property
    def provider(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

    @property
    def supports_pdf_input(self) -> bool:
        return True

    def _default_max_tokens(self, max_tokens: int | None) -> int | None:
        if max_tokens is not None:
            return max_tokens
        configured = self._options.get("max_output_tokens")
        return int(configured) if isinstance(configured, int | float) else None

    def _record_usage(self, usage: types.GenerateContentResponseUsageMetadata | None) -> None:
        if usage is None:
            return
        self._usage.record(
            UsageRecord(
                kind="llm",
                provider="gemini",
                model=self._model,
                tokens_in=usage.prompt_token_count or 0,
                tokens_out=usage.candidates_token_count or 0,
            )
        )

    def _check_refusal(self, response: types.GenerateContentResponse) -> None:
        if not response.candidates:
            return
        reason = response.candidates[0].finish_reason
        if reason in _REFUSAL_REASONS:
            raise ProviderRefusal(f"gemini declined to generate (finish_reason={reason})")

    def generate(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self._default_max_tokens(max_tokens),
        )
        contents = _contents_for(messages)

        def call() -> list[types.GenerateContentResponse]:
            return list(
                self._client.models.generate_content_stream(
                    model=self._model,
                    contents=contents,  # type: ignore[arg-type]  # SDK union is list-invariant
                    config=config,
                )
            )

        try:
            chunks = with_backoff(
                call, is_retryable=gemini_retry_hint, max_retries=self._max_retries
            )
        except Exception as exc:
            raise to_provider_error(exc) from exc

        for chunk in chunks:
            self._check_refusal(chunk)
            self._record_usage(chunk.usage_metadata)
            if chunk.text:
                yield chunk.text

    def generate_structured(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        schema: type[TModel],
        max_tokens: int | None = None,
    ) -> TModel:
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self._default_max_tokens(max_tokens),
            response_mime_type="application/json",
            response_schema=schema,
        )
        contents = _contents_for(messages)

        def call() -> types.GenerateContentResponse:
            return self._client.models.generate_content(
                model=self._model,
                contents=contents,  # type: ignore[arg-type]  # SDK union is list-invariant
                config=config,
            )

        last_error: Exception | None = None
        for _ in range(2):  # one call + one validation retry, per ARCHITECTURE.md §3
            try:
                response = with_backoff(
                    call, is_retryable=gemini_retry_hint, max_retries=self._max_retries
                )
            except Exception as exc:
                raise to_provider_error(exc) from exc

            self._record_usage(response.usage_metadata)
            self._check_refusal(response)

            parsed = response.parsed
            if isinstance(parsed, schema):
                return parsed
            try:
                return schema.model_validate_json(response.text or "")
            except (ValidationError, ValueError) as exc:
                last_error = exc
                continue

        raise ProviderInvalidResponse(
            f"gemini structured output failed to validate against "
            f"{schema.__name__} after retry: {last_error}"
        )

    def attach_pdf(self, *, data: bytes, display_name: str) -> ContentRef:
        def call() -> types.File:
            return self._client.files.upload(
                file=io.BytesIO(data),
                config=types.UploadFileConfig(
                    mime_type="application/pdf", display_name=display_name
                ),
            )

        try:
            uploaded = with_backoff(
                call, is_retryable=gemini_retry_hint, max_retries=self._max_retries
            )
        except Exception as exc:
            raise to_provider_error(exc) from exc

        if not uploaded.uri:
            raise ProviderUnavailable("gemini file upload returned no URI")
        return ContentRef(provider="gemini", ref=uploaded.uri, mime_type="application/pdf")
