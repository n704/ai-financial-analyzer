"""P6.1: the ``market_data``/``forecast`` config blocks validate at load, and
the factory's three boot checks — license gate, ``forecast`` extra importable,
``max_context``/``max_horizon`` within the adapter's limits — each fail at
startup with a distinct, readable message. Plus the license table and the
pure helpers of the TimesFM adapter that need no torch."""

from __future__ import annotations

import importlib.util

import pytest
from pydantic import ValidationError

from app.config import ConfigError, Settings, is_bar_interval
from app.providers.base import ForecastUnavailable
from app.providers.factory import (
    build_forecast_provider,
    build_forecast_providers,
    build_market_data_provider,
    check_forecast_limits,
)
from app.providers.forecast.fake import FakeForecastProvider
from app.providers.forecast.licenses import (
    APACHE_2,
    TIMESFM_NON_COMMERCIAL,
    UNKNOWN_LICENSE,
    check_weights_license,
    lookup_weights_license,
)
from app.providers.forecast.naive import NaiveForecastProvider
from app.providers.forecast.timesfm import TIMESFM_HEAD_LEVELS, quantile_columns
from app.providers.marketdata.fixture import FixtureMarketDataProvider

_TIMESFM_INSTALLED = importlib.util.find_spec("timesfm") is not None


def _settings(**overrides: object) -> Settings:
    raw: dict[str, object] = {
        "llm": {"provider": "fake", "model": "fake-llm"},
        "embeddings": {"provider": "fake", "model": "fake-embedding"},
        "vector_store": {"provider": "chroma", "path": "./data/x"},
        "database": {"url": "sqlite:///:memory:"},
    }
    raw.update(overrides)
    return Settings.model_validate(raw)


# --------------------------------------------------------------------------- #
# Config validation
# --------------------------------------------------------------------------- #
def test_forecast_defaults_are_off_and_sane() -> None:
    s = _settings()
    assert s.forecast.enabled is False
    assert s.forecast.provider == "naive"
    assert s.forecast.model == "google/timesfm-2.5-200m-pytorch"
    assert s.forecast.transform == "log"
    assert s.market_data.provider == "fixture"
    assert s.limits.max_forecast_horizon == 120
    assert s.limits.quotas.forecasts_per_day == 50


@pytest.mark.parametrize(
    "quantiles,message",
    [
        ([0.1, 0.9], "0.5"),
        ([0.9, 0.5, 0.1], "increasing"),
        ([0.0, 0.5, 0.9], "between 0 and 1"),
    ],
)
def test_quantiles_must_include_median_and_band(quantiles: list[float], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        _settings(forecast={"quantiles": quantiles})


def test_interval_must_be_a_bar_interval() -> None:
    with pytest.raises(ConfigError, match=r"market_data\.interval"):
        _settings(market_data={"interval": "daily"})
    assert _settings(market_data={"interval": "5m"}).market_data.is_intraday is True
    assert is_bar_interval("1wk") and not is_bar_interval("week")


def test_api_horizon_cap_cannot_exceed_model_horizon_when_enabled() -> None:
    with pytest.raises(ConfigError, match="max_forecast_horizon"):
        _settings(
            forecast={"enabled": True, "max_horizon": 60}, limits={"max_forecast_horizon": 120}
        )
    # Disabled: the cap is inert, so the combination is allowed.
    _settings(forecast={"enabled": False, "max_horizon": 60}, limits={"max_forecast_horizon": 120})


def test_unknown_forecast_key_is_rejected() -> None:
    with pytest.raises(ValidationError):  # the loader wraps this into ConfigError
        _settings(forecast={"modle": "x"})


# --------------------------------------------------------------------------- #
# Factory + boot checks
# --------------------------------------------------------------------------- #
def test_disabled_forecasting_builds_nothing() -> None:
    assert build_forecast_providers(_settings()) is None


def test_naive_and_fake_providers_build_from_config() -> None:
    naive = build_forecast_provider(_settings(forecast={"options": {"method": "seasonal_naive"}}))
    assert isinstance(naive, NaiveForecastProvider)
    assert naive.model == "naive:seasonal_naive"
    fake = build_forecast_provider(_settings(forecast={"provider": "fake"}))
    assert isinstance(fake, FakeForecastProvider)
    pair = build_forecast_providers(_settings(forecast={"enabled": True}))
    assert pair is not None
    assert isinstance(pair.market_data, FixtureMarketDataProvider)
    assert isinstance(pair.forecast, NaiveForecastProvider)


def test_unknown_providers_fail_fast() -> None:
    with pytest.raises(ConfigError, match=r"forecast\.provider"):
        build_forecast_provider(_settings(forecast={"provider": "prophet"}))
    with pytest.raises(ConfigError, match=r"market_data\.provider"):
        build_market_data_provider(_settings(market_data={"provider": "bloomberg"}))


def test_boot_check_license_gate_refuses_restricted_weights() -> None:
    settings = _settings(
        forecast={"enabled": True, "provider": "timesfm", "model": "google/timesfm-3.0-pytorch"}
    )
    with pytest.raises(ConfigError, match="weights_license_ack"):
        build_forecast_providers(settings)


def test_boot_check_license_gate_denies_unknown_checkpoints() -> None:
    settings = _settings(
        forecast={"enabled": True, "provider": "timesfm", "model": "someone/mystery-weights"}
    )
    with pytest.raises(ConfigError, match="denied by default"):
        build_forecast_providers(settings)


@pytest.mark.skipif(_TIMESFM_INSTALLED, reason="the forecast extra is installed here")
def test_boot_check_extra_missing_is_a_config_error() -> None:
    settings = _settings(forecast={"enabled": True, "provider": "timesfm"})
    with pytest.raises(ConfigError, match="`forecast` extra"):
        build_forecast_providers(settings)


def test_boot_check_limits_against_adapter() -> None:
    naive = NaiveForecastProvider()
    with pytest.raises(ConfigError, match="max_context"):
        check_forecast_limits(_settings(forecast={"max_context": 20_000}), naive)
    with pytest.raises(ConfigError, match=r"forecast\.max_horizon"):
        check_forecast_limits(_settings(forecast={"max_horizon": 5_000}), naive)
    check_forecast_limits(_settings(), naive)


def test_boot_check_intraday_needs_capable_source() -> None:
    settings = _settings(forecast={"enabled": True}, market_data={"interval": "5m"})
    with pytest.raises(ConfigError, match="supports_intraday"):
        build_forecast_providers(settings)


# --------------------------------------------------------------------------- #
# License table
# --------------------------------------------------------------------------- #
def test_license_table() -> None:
    assert lookup_weights_license("google/timesfm-2.5-200m-pytorch").license == APACHE_2
    assert lookup_weights_license("google/timesfm-2.0-500m-pytorch").restricted is False
    assert lookup_weights_license("google/timesfm-1.0-200m").restricted is False
    three = lookup_weights_license("google/timesfm-3.0-pytorch")
    assert three.license == TIMESFM_NON_COMMERCIAL and three.restricted
    assert lookup_weights_license("acme/other") is UNKNOWN_LICENSE
    with pytest.raises(ConfigError):
        check_weights_license("google/timesfm-3.0-pytorch", ack=False)
    assert check_weights_license("google/timesfm-3.0-pytorch", ack=True).restricted
    assert check_weights_license("GOOGLE/TimesFM-2.5-200m-pytorch", ack=False).license == APACHE_2


# --------------------------------------------------------------------------- #
# TimesFM adapter pure helpers (no torch needed)
# --------------------------------------------------------------------------- #
def test_quantile_columns_handles_both_head_layouts() -> None:
    assert quantile_columns(9, (0.1, 0.5, 0.9), TIMESFM_HEAD_LEVELS) == [0, 4, 8]
    assert quantile_columns(10, (0.1, 0.5, 0.9), TIMESFM_HEAD_LEVELS) == [1, 5, 9]
    with pytest.raises(ForecastUnavailable):
        quantile_columns(7, (0.5,), TIMESFM_HEAD_LEVELS)
    with pytest.raises(ForecastUnavailable):
        quantile_columns(9, (0.55,), TIMESFM_HEAD_LEVELS)
