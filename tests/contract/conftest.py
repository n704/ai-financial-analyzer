"""Shared fixtures for the P1.7 adapter contract suite (ARCHITECTURE.md §8).

Every ``LLMProvider``/``EmbeddingProvider`` adapter must satisfy the same tests
in this package. ``fake`` always runs (no network, no key). ``gemini`` runs only
when ``GEMINI_API_KEY`` is set in the environment — it makes real, billed (free
tier) calls, so it's skipped rather than faked in CI/local runs without a key.
Adding a new adapter means adding one entry to the factories below; the tests
themselves don't change.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest

from app.providers.base import EmbeddingProvider, LLMProvider
from app.providers.embeddings.fake import FakeEmbeddingProvider
from app.providers.llm.fake import FakeLLMProvider


def _gemini_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _build_gemini_llm() -> LLMProvider:
    from app.providers.llm.gemini import GeminiLLMProvider

    return GeminiLLMProvider(api_key=os.environ["GEMINI_API_KEY"], model="gemini-2.5-flash")


def _build_gemini_embeddings() -> EmbeddingProvider:
    from app.providers.embeddings.gemini import GeminiEmbeddingProvider

    return GeminiEmbeddingProvider(
        api_key=os.environ["GEMINI_API_KEY"],
        model="gemini-embedding-001",
        dimension=768,
    )


_skip_no_key = pytest.mark.skipif(not _gemini_available(), reason="GEMINI_API_KEY not set")

LLM_FACTORIES: dict[str, Callable[[], LLMProvider]] = {
    "fake": lambda: FakeLLMProvider(),
    "gemini": _build_gemini_llm,
}
EMBEDDING_FACTORIES: dict[str, Callable[[], EmbeddingProvider]] = {
    "fake": lambda: FakeEmbeddingProvider(dimension=16),
    "gemini": _build_gemini_embeddings,
}

_LLM_PARAMS = ["fake", pytest.param("gemini", marks=_skip_no_key)]
_EMBEDDING_PARAMS = ["fake", pytest.param("gemini", marks=_skip_no_key)]


@pytest.fixture(params=_LLM_PARAMS)
def llm_provider(request: pytest.FixtureRequest) -> LLMProvider:
    return LLM_FACTORIES[request.param]()


@pytest.fixture(params=_EMBEDDING_PARAMS)
def embedding_provider(request: pytest.FixtureRequest) -> EmbeddingProvider:
    return EMBEDDING_FACTORIES[request.param]()
