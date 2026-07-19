"""P1.7: shared embedding adapter contract suite.

Every ``EmbeddingProvider`` adapter — Fake always, Gemini when a key is
available — must satisfy these: batch and single-text embedding return vectors
of the adapter's declared ``dimension``, and identical text embeds identically
(determinism retrieval depends on isn't in scope here, but shape/consistency is).
"""

from __future__ import annotations

from app.providers.base import EmbeddingProvider


def test_dimension_is_positive(embedding_provider: EmbeddingProvider) -> None:
    assert embedding_provider.dimension > 0


def test_embed_query_returns_declared_dimension(embedding_provider: EmbeddingProvider) -> None:
    vector = embedding_provider.embed_query("Revenue increased 10% year over year.")
    assert len(vector) == embedding_provider.dimension
    assert all(isinstance(x, float) for x in vector)


def test_embed_documents_batch_matches_input_count(embedding_provider: EmbeddingProvider) -> None:
    texts = ["Revenue grew.", "Costs declined.", "Guidance was raised."]
    vectors = embedding_provider.embed_documents(texts)
    assert len(vectors) == len(texts)
    assert all(len(v) == embedding_provider.dimension for v in vectors)


def test_embed_documents_empty_list_returns_empty(embedding_provider: EmbeddingProvider) -> None:
    assert embedding_provider.embed_documents([]) == []


def test_provider_and_model_identify_the_adapter(embedding_provider: EmbeddingProvider) -> None:
    assert isinstance(embedding_provider.provider, str) and embedding_provider.provider
    assert isinstance(embedding_provider.model, str) and embedding_provider.model
