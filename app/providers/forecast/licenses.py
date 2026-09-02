"""Weights-license gate for forecast checkpoints (ARCHITECTURE.md §3, "Forecast
weights & the license guard") — the embedding-space guard's sibling.

TimesFM's *source* is Apache-2.0 in every version; it is the **3.0 weights**
that ship under ``timesfm-non-commercial-license-v1.0`` (non-commercial,
non-production). A production-targeted app cannot default to them, so 2.5 is
the default and anything restricted — or unknown — refuses to load unless the
operator sets ``forecast.weights_license_ack: true``. Checked at startup by the
factory, before any download; never at request time.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import ConfigError

APACHE_2 = "Apache-2.0"
TIMESFM_NON_COMMERCIAL = "timesfm-non-commercial-license-v1.0"


@dataclass(frozen=True, slots=True)
class WeightsLicense:
    license: str
    restricted: bool
    note: str = ""


# Longest prefix wins; matched case-insensitively against `forecast.model`.
_KNOWN: tuple[tuple[str, WeightsLicense], ...] = (
    ("google/timesfm-2.5-", WeightsLicense(APACHE_2, restricted=False)),
    ("google/timesfm-2.0-", WeightsLicense(APACHE_2, restricted=False)),
    ("google/timesfm-1.0-", WeightsLicense(APACHE_2, restricted=False)),
    (
        "google/timesfm-3.0",
        WeightsLicense(
            TIMESFM_NON_COMMERCIAL,
            restricted=True,
            note="non-commercial, non-production use only",
        ),
    ),
)

UNKNOWN_LICENSE = WeightsLicense(
    "unknown", restricted=True, note="not in the known-checkpoint table; denied by default"
)


def lookup_weights_license(model: str) -> WeightsLicense:
    """The license of a checkpoint id, or :data:`UNKNOWN_LICENSE` (restricted)."""
    key = model.strip().lower()
    best: tuple[int, WeightsLicense] | None = None
    for prefix, entry in _KNOWN:
        if key.startswith(prefix.lower()) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), entry)
    return best[1] if best is not None else UNKNOWN_LICENSE


def check_weights_license(model: str, *, ack: bool) -> WeightsLicense:
    """Fail fast (``ConfigError``) when ``model``'s weights are restricted and
    the operator has not acknowledged the license. Returns the license entry
    so the caller can log which terms the loaded weights carry."""
    entry = lookup_weights_license(model)
    if entry.restricted and not ack:
        detail = f" ({entry.note})" if entry.note else ""
        raise ConfigError(
            f"forecast.model={model!r} carries weights license {entry.license!r}{detail}. "
            f"Loading it requires forecast.weights_license_ack: true — set it only if "
            f"this deployment's use is permitted under those terms. The default, "
            f"'google/timesfm-2.5-200m-pytorch', is Apache-2.0 and needs no acknowledgement."
        )
    return entry


__all__ = [
    "APACHE_2",
    "TIMESFM_NON_COMMERCIAL",
    "UNKNOWN_LICENSE",
    "WeightsLicense",
    "check_weights_license",
    "lookup_weights_license",
]
