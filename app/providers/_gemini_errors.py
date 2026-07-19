"""Gemini SDK error classification shared by the LLM and embedding adapters.

Internal helper — not part of the public provider surface (no re-export from
``app/providers/__init__.py``). Both ``llm/gemini.py`` and ``embeddings/gemini.py``
hit the same ``google.genai.errors.APIError`` shape, so the retryability and
typed-error mapping live here once instead of twice.
"""

from __future__ import annotations

from google.genai import errors

from app.providers.base import ProviderRateLimited, ProviderUnavailable

_RETRYABLE_CODES = {429, 500, 502, 503, 504}


def gemini_retry_hint(exc: Exception) -> float | None:
    """``with_backoff``-shaped classifier: 0.0 = retry now, None = don't retry."""
    if isinstance(exc, errors.APIError) and exc.code in _RETRYABLE_CODES:
        return 0.0
    return None


def to_provider_error(exc: Exception) -> Exception:
    """Normalize a Gemini SDK exception into a typed provider error."""
    if isinstance(exc, errors.APIError):
        if exc.code == 429:
            return ProviderRateLimited(str(exc))
        return ProviderUnavailable(str(exc))
    return exc
