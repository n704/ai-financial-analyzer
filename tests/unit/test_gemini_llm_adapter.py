"""P1.5/P1.7: Gemini LLM adapter — backoff, refusal, and structured-retry paths.

These monkeypatch the SDK call sites directly (no network, no API key needed)
so the 429-backoff and validation-retry logic — which the live contract suite
can't reliably exercise against a real, well-behaved API — gets covered here.
"""

from __future__ import annotations

from typing import Any

import pytest
from google.genai import errors, types
from pydantic import BaseModel

from app.providers.base import Message, ProviderRateLimited, ProviderRefusal
from app.providers.llm.gemini import GeminiLLMProvider


class _Sample(BaseModel):
    headline: str


def _make_provider() -> GeminiLLMProvider:
    return GeminiLLMProvider(api_key="test-key", model="gemini-2.5-flash", max_retries=3)


def _rate_limit_error() -> errors.APIError:
    detail = {"message": "rate limited", "status": "RESOURCE_EXHAUSTED"}
    return errors.APIError(429, {"error": detail})


def _response(text: str, finish_reason: types.FinishReason = types.FinishReason.STOP) -> Any:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part.from_text(text=text)]),
                finish_reason=finish_reason,
            )
        ]
    )


def test_generate_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider()
    calls = {"n": 0}

    def fake_stream(*, model: str, contents: object, config: object) -> list[Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _rate_limit_error()
        return [_response("hello there")]

    monkeypatch.setattr(provider._client.models, "generate_content_stream", fake_stream)
    monkeypatch.setattr("app.providers.retry.random.uniform", lambda a, b: 0.0)
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda _s: None)

    text = "".join(provider.generate(system="s", messages=[Message(role="user", content="hi")]))
    assert text == "hello there"
    assert calls["n"] == 2


def test_generate_raises_typed_error_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GeminiLLMProvider(api_key="test-key", model="gemini-2.5-flash", max_retries=1)

    def always_fails(*, model: str, contents: object, config: object) -> list[Any]:
        raise _rate_limit_error()

    monkeypatch.setattr(provider._client.models, "generate_content_stream", always_fails)
    monkeypatch.setattr("app.providers.retry.random.uniform", lambda a, b: 0.0)
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda _s: None)

    with pytest.raises(ProviderRateLimited):
        list(provider.generate(system="s", messages=[Message(role="user", content="hi")]))


def test_generate_raises_refusal_on_safety_finish_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider()

    def fake_stream(*, model: str, contents: object, config: object) -> list[Any]:
        return [_response("", finish_reason=types.FinishReason.SAFETY)]

    monkeypatch.setattr(provider._client.models, "generate_content_stream", fake_stream)

    with pytest.raises(ProviderRefusal):
        list(provider.generate(system="s", messages=[Message(role="user", content="hi")]))


def test_generate_structured_returns_parsed_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider()
    expected = _Sample(headline="Revenue grew 10%")

    def fake_generate(*, model: str, contents: object, config: object) -> Any:
        resp = _response('{"headline": "Revenue grew 10%"}')
        resp.parsed = expected
        return resp

    monkeypatch.setattr(provider._client.models, "generate_content", fake_generate)

    result = provider.generate_structured(
        system="s", messages=[Message(role="user", content="extract")], schema=_Sample
    )
    assert result == expected


def test_generate_structured_falls_back_to_manual_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `.parsed` isn't populated (e.g. SDK didn't recognize the schema
    shape) the adapter must still validate the raw text against the schema."""
    provider = _make_provider()

    def fake_generate(*, model: str, contents: object, config: object) -> Any:
        return _response('{"headline": "Manual path works"}')

    monkeypatch.setattr(provider._client.models, "generate_content", fake_generate)

    result = provider.generate_structured(
        system="s", messages=[Message(role="user", content="extract")], schema=_Sample
    )
    assert result.headline == "Manual path works"


def test_generate_structured_raises_invalid_after_one_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    calls = {"n": 0}

    def fake_generate(*, model: str, contents: object, config: object) -> Any:
        calls["n"] += 1
        return _response("not valid json at all")

    monkeypatch.setattr(provider._client.models, "generate_content", fake_generate)

    from app.providers.base import ProviderInvalidResponse

    with pytest.raises(ProviderInvalidResponse):
        provider.generate_structured(
            system="s", messages=[Message(role="user", content="extract")], schema=_Sample
        )
    assert calls["n"] == 2  # one call + one validation retry, per ARCHITECTURE.md §3
