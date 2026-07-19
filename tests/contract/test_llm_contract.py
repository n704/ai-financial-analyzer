"""P1.7: shared LLM adapter contract suite.

Every ``LLMProvider`` adapter — Fake always, Gemini when a key is available —
must satisfy these: streaming generation produces text, structured output
round-trips through a Pydantic schema, capability flags are well-typed, and a
PDF attachment either succeeds or explicitly declines via ``NotImplementedError``
(never a vendor exception leaking through). 429 backoff and error-normalization
for the *real* SDK are covered by adapter-specific unit tests (e.g.
``tests/unit/test_gemini_llm_adapter.py``) since only a fake can safely and
deterministically inject an HTTP 429 without hitting the network.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.providers.base import LLMProvider, Message


class _Extraction(BaseModel):
    headline: str
    confidence: float | None


def test_generate_streams_nonempty_text(llm_provider: LLMProvider) -> None:
    chunks = list(
        llm_provider.generate(
            system="You are terse.",
            messages=[Message(role="user", content="Say hello in one short sentence.")],
            max_tokens=64,
        )
    )
    assert "".join(chunks).strip()


def test_generate_structured_round_trips_schema(llm_provider: LLMProvider) -> None:
    result = llm_provider.generate_structured(
        system="Extract the requested fields as JSON.",
        messages=[
            Message(
                role="user",
                content=(
                    "Revenue grew 12% year over year, driven by strong cloud demand. "
                    "Give me a one-sentence headline and a confidence score between 0 and 1."
                ),
            )
        ],
        schema=_Extraction,
    )
    assert isinstance(result, _Extraction)
    assert isinstance(result.headline, str)


def test_supports_pdf_input_is_bool(llm_provider: LLMProvider) -> None:
    assert isinstance(llm_provider.supports_pdf_input, bool)


def test_provider_and_model_identify_the_adapter(llm_provider: LLMProvider) -> None:
    assert isinstance(llm_provider.provider, str) and llm_provider.provider
    assert isinstance(llm_provider.model, str) and llm_provider.model


def test_attach_pdf_either_supported_or_explicitly_not(llm_provider: LLMProvider) -> None:
    minimal_pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    if llm_provider.supports_pdf_input:
        ref = llm_provider.attach_pdf(data=minimal_pdf, display_name="contract-test.pdf")
        assert ref.provider == llm_provider.provider
        assert ref.ref
    else:
        try:
            llm_provider.attach_pdf(data=minimal_pdf, display_name="contract-test.pdf")
        except NotImplementedError:
            pass
        else:
            raise AssertionError(
                "supports_pdf_input=False but attach_pdf did not raise NotImplementedError"
            )
