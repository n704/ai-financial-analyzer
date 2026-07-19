"""Load and validate ``config.yaml`` into a typed :class:`Settings`.

Flow: pick the path (arg → ``APP_CONFIG`` env → ``config/dev.yaml``), parse YAML,
interpolate ``${VAR}`` references from the environment (connection strings for the
scaled profile), then validate. Any failure raises :class:`ConfigError` with a
message that names the offending key or env var — invalid config fails fast.

Secrets are *not* interpolated here: ``api_key_env`` stays a name and is resolved
lazily by the adapter that needs it, so the secret never lands in ``Settings``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.config.errors import ConfigError
from app.config.models import Settings

DEFAULT_CONFIG_PATH = "config/dev.yaml"
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _interpolate(value: Any, *, path: str) -> Any:
    """Recursively replace ``${VAR}`` in string values with env values.

    ``path`` tracks the dotted config location purely for error messages.
    """
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            var = match.group(1)
            env = os.environ.get(var)
            if env is None:
                raise ConfigError(
                    f"config key '{path}' references ${{{var}}}, "
                    f"but environment variable {var} is not set"
                )
            return env

        return _ENV_REF.sub(replace, value)
    if isinstance(value, dict):
        return {
            k: _interpolate(v, path=f"{path}.{k}" if path else str(k)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_interpolate(v, path=f"{path}[{i}]") for i, v in enumerate(value)]
    return value


def load_settings(config_path: str | os.PathLike[str] | None = None) -> Settings:
    """Load, interpolate, and validate configuration into :class:`Settings`."""
    path = Path(config_path or os.environ.get("APP_CONFIG", DEFAULT_CONFIG_PATH))
    if not path.is_file():
        raise ConfigError(
            f"config file not found: {path} "
            f"(set APP_CONFIG or pass a path; default is {DEFAULT_CONFIG_PATH})"
        )

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file {path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path} must contain a YAML mapping at the top level")

    interpolated = _interpolate(raw, path="")

    try:
        return Settings.model_validate(interpolated)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {path}:\n{exc}") from exc
