"""Deterministic fake embedding provider (P1.4).

Hashes each text into a fixed-dimension unit vector — deterministic (same text →
same vector every run, across processes) and cheap, so retrieval tests can assert
on similarity ordering without a network call or a real model.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence


class FakeEmbeddingProvider:
    """A deterministic :class:`~app.providers.base.EmbeddingProvider`."""

    def __init__(self, *, model: str = "fake-embedding", dimension: int = 16) -> None:
        if dimension < 1:
            raise ValueError("dimension must be >= 1")
        self._model = model
        self._dimension = dimension

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> list[float]:
        # Repeated hashing gives `dimension` independent-looking bytes-streams from
        # one text, then each is folded to a signed float and L2-normalized so
        # cosine similarity behaves sensibly in tests.
        vec: list[float] = []
        seed = text.encode("utf-8")
        counter = 0
        while len(vec) < self._dimension:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for j in range(0, len(digest), 4):
                if len(vec) >= self._dimension:
                    break
                chunk = digest[j : j + 4]
                as_int = int.from_bytes(chunk, "big", signed=False)
                # Map to [-1, 1).
                vec.append((as_int / 2**32) * 2 - 1)
            counter += 1
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]
