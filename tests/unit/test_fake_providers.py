"""P1.4: the fake LLM/embedding providers are the zero-key dev/test backbone."""

from __future__ import annotations

from pydantic import BaseModel

from app.providers.base import Message, ProviderRateLimited
from app.providers.embeddings.fake import FakeEmbeddingProvider
from app.providers.llm.fake import FakeLLMProvider


class _Metrics(BaseModel):
    revenue: float | None
    company: str
    source_page: int | None = None


def test_fake_llm_generate_streams_and_joins() -> None:
    llm = FakeLLMProvider(scripted_text=["hello world from fake"])
    chunks = list(llm.generate(system="sys", messages=[Message(role="user", content="hi")]))
    assert "".join(chunks) == "hello world from fake"
    assert len(chunks) > 1  # actually streamed, not one blob


def test_fake_llm_generate_structured_fabricates_when_unscripted() -> None:
    llm = FakeLLMProvider()
    result = llm.generate_structured(
        system="sys", messages=[Message(role="user", content="extract")], schema=_Metrics
    )
    assert isinstance(result, _Metrics)
    assert result.revenue is None  # optional fields default to None, never invented
    assert result.company == "fake"


def test_fake_llm_generate_structured_uses_script() -> None:
    scripted = _Metrics(revenue=123.4, company="Acme", source_page=42)
    llm = FakeLLMProvider(structured={_Metrics: scripted})
    result = llm.generate_structured(
        system="sys", messages=[Message(role="user", content="extract")], schema=_Metrics
    )
    assert result is scripted


def test_fake_llm_error_script_raises_typed_error() -> None:
    llm = FakeLLMProvider(error_script=[ProviderRateLimited("slow down", retry_after=1.0)])
    try:
        list(llm.generate(system="s", messages=[]))
    except ProviderRateLimited as exc:
        assert exc.retry_after == 1.0
    else:
        raise AssertionError("expected ProviderRateLimited")


def test_fake_llm_attach_pdf_deterministic() -> None:
    llm = FakeLLMProvider()
    ref1 = llm.attach_pdf(data=b"pdf-bytes", display_name="a.pdf")
    ref2 = llm.attach_pdf(data=b"pdf-bytes", display_name="b.pdf")
    assert ref1.ref == ref2.ref  # same content → same ref
    assert ref1.provider == "fake"


def test_fake_llm_no_pdf_support_raises() -> None:
    llm = FakeLLMProvider(supports_pdf_input=False)
    assert llm.supports_pdf_input is False
    try:
        llm.attach_pdf(data=b"x", display_name="x.pdf")
    except NotImplementedError:
        pass
    else:
        raise AssertionError("expected NotImplementedError")


def test_fake_embedding_deterministic_and_dimension() -> None:
    emb = FakeEmbeddingProvider(dimension=8)
    v1 = emb.embed_query("revenue grew 10%")
    v2 = emb.embed_query("revenue grew 10%")
    assert v1 == v2
    assert len(v1) == 8
    assert emb.dimension == 8


def test_fake_embedding_documents_batch() -> None:
    emb = FakeEmbeddingProvider(dimension=4)
    vecs = emb.embed_documents(["a", "b", "a"])
    assert vecs[0] == vecs[2]
    assert vecs[0] != vecs[1]


def test_fake_embedding_similar_text_more_similar_than_different() -> None:
    import math

    emb = FakeEmbeddingProvider(dimension=32)

    def cos(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True)) / (
            math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
        )

    v_a = emb.embed_query("net income increased")
    v_a2 = emb.embed_query("net income increased")  # identical text
    v_b = emb.embed_query("completely unrelated risk factor disclosure")

    assert cos(v_a, v_a2) > cos(v_a, v_b)
