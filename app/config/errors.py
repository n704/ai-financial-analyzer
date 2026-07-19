"""Config-layer errors.

Kept separate so the loader and models can raise a single, catchable type that
the app factory turns into a clear fail-fast message at startup.
"""

from __future__ import annotations


class ConfigError(Exception):
    """Raised when configuration is missing, malformed, or internally inconsistent."""
