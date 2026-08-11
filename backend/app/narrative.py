"""Plain-English readings of the charts, built from the numbers behind them.

Every sentence here is derived from values `analysis.py` already computed, so
the prose cannot drift from what the chart shows and needs no model, API key or
network call. The tone is deliberately deflationary: the hold-out numbers in the
README show this model often fails to beat "assume no change", and an
explanation that reads like a recommendation would be worse than none.

Each function returns a list of {"title", "body"} paragraphs.
"""
from __future__ import annotations

# Band width as a multiple of what the stock's own realized volatility implies.
TIGHT_BAND = 0.6
WIDE_BAND = 1.6
# |conviction| = |mean return| / spread across paths.
STRONG_CONVICTION = 0.5
WEAK_CONVICTION = 0.15
# A p10-p90 band should contain the truth about 80% of the time.
TARGET_COVERAGE = 80.0
COVERAGE_SLACK = 15.0


def _para(title: str, body: str) -> dict:
    return {"title": title, "body": body}


def _num(value, digits=2, suffix=""):
    """Format a possibly-None number. `analysis._f` returns None for NaN/inf."""
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def _signed(value, digits=2, suffix="%"):
    return "—" if value is None else f"{value:+.{digits}f}{suffix}"


def _direction(value, up="rises", down="falls", flat="is unchanged") -> str:
    if value is None:
        return flat
    return up if value > 0 else down if value < 0 else flat


def explain_forecast(stats: dict, band: list[dict], params: dict, interval_label: str,
                     technicals: dict | None = None) -> list[dict]:
    """Read the main chart: the fan, the band and where the median lands."""
    out: list[dict] = []
    horizon = params.get("horizon")
    bars = f"{horizon} {interval_label.lower()} bar{'s' if horizon != 1 else ''}"
    n_paths = stats.get("n_paths")

    out.append(
        _para(
            "What the fan is",
            f"The faint lines after the last candle are {n_paths} separate futures Kronos sampled "
            f"from the same history — not {n_paths} opinions, but {n_paths} draws from one "
            "distribution. The solid blue line is their median (p50) and the dashed lines are the "
            "10th and 90th percentiles, so roughly eight of every ten sampled futures finish inside "
            "them. Read the width of that band as the model's uncertainty, and the slope of the "
            "median as its central guess.",
        )
    )

    expected = stats.get("expected_return_pct")
    median_close = stats.get("median_close")
    last_close = stats.get("last_close")
    body = (
        f"Over the next {bars} the median path {_direction(expected)} from "
        f"{_num(last_close)} to {_num(median_close)}, a move of {_signed(expected)}. "
    )
    final = band[-1] if band else {}
    if final.get("p25") is not None and final.get("p75") is not None:
        body += (
            f"Half the sampled futures finish between {_num(final['p25'])} and "
            f"{_num(final['p75'])}, and eight in ten between {_num(final.get('p10'))} and "
            f"{_num(final.get('p90'))} — "
        )
    else:
        body += "In return terms that is "
    body += (
        f"{_signed(stats.get('return_p10_pct'))} to {_signed(stats.get('return_p90_pct'))} "
        "against today's close."
    )
    out.append(_para("Where the median lands", body))

    out.append(_band_width(stats, band, technicals, bars))
    out.append(_probability(stats))
    return out


def _band_width(stats: dict, band: list[dict], technicals: dict | None, bars: str) -> dict:
    """Compare the terminal band width against the stock's own volatility.

    A ±4% band means nothing in isolation: it is tight for a meme stock and
    absurdly wide for a utility. Scaling by realized vol over the same number of
    bars is what makes the number readable.
    """
    p10, p90 = stats.get("return_p10_pct"), stats.get("return_p90_pct")
    if p10 is None or p90 is None:
        return _para(
            "How wide the band is",
            "The sampled futures were too degenerate to measure a spread, which usually means the "
            "price series fed to the model was flat or the path count was very low.",
        )

    width = p90 - p10
    body = (
        f"By the end of the horizon the band spans {_num(width, 1, '%')} — from "
        f"{_signed(p10)} to {_signed(p90)}. "
    )

    realized = (technicals or {}).get("realized_vol_annual")
    horizon_bars = stats.get("horizon_bars")
    if realized and horizon_bars:
        # Annualised vol scaled to the horizon, then to a ~10th-90th spread
        # (±1.28σ) so the two numbers are measured the same way.
        expected_width = realized * 100 * (horizon_bars / 252) ** 0.5 * 2 * 1.2816
        ratio = width / expected_width if expected_width else None
        if ratio is not None:
            body += (
                f"The stock's own realized volatility over the same {horizon_bars} bars implies a "
                f"spread near {_num(expected_width, 1, '%')}, so this band is "
            )
            if ratio < TIGHT_BAND:
                body += (
                    "notably tighter than history. The model is more confident than the stock's "
                    "past behaviour justifies — treat the band as optimistic."
                )
            elif ratio > WIDE_BAND:
                body += (
                    "much wider than history. The model is hedging, so the median direction "
                    "carries little information."
                )
            else:
                body += "in line with how this stock normally moves."
    else:
        body += f"There is no realized-volatility baseline to compare it against over {bars}."

    return _para("How wide the band is", body)


def _probability(stats: dict) -> dict:
    prob_up = stats.get("prob_up")
    conviction = stats.get("conviction")
    pct = None if prob_up is None else prob_up * 100

    body = (
        f"{_num(pct, 0, '%')} of the sampled futures end above today's close. That is a count of "
        "paths, not a probability the stock goes up — it only describes this model, on this "
        "history, with no knowledge of earnings, news or fundamentals. "
    )

    if conviction is None:
        body += "Conviction could not be computed for these paths."
    elif abs(conviction) >= STRONG_CONVICTION:
        body += (
            f"Conviction (mean move ÷ spread) is {_signed(conviction, 2, '')}, which is high: the "
            "paths mostly agree with each other."
        )
    elif abs(conviction) <= WEAK_CONVICTION:
        body += (
            f"Conviction (mean move ÷ spread) is only {_signed(conviction, 2, '')}, so the average "
            "move is small next to the disagreement between paths — this is noise more than signal."
        )
    else:
        body += (
            f"Conviction (mean move ÷ spread) is {_signed(conviction, 2, '')}, a moderate lean "
            "rather than a strong one."
        )

    return _para("What the probability means", body)


def explain_backtest(backtest: dict | None) -> list[dict]:
    """Read the hold-out chart: forecast against bars the model never saw."""
    if not backtest:
        return []

    bars = backtest.get("bars")
    mape = backtest.get("mape_pct")
    naive = backtest.get("naive_mape_pct")
    beat = backtest.get("beats_naive")

    out = [
        _para(
            "What this chart is",
            f"The last {bars} bars were hidden from the model. It forecast them from the bars "
            "before, and the result is scored against what actually happened. The white line is "
            "reality, blue is the forecast median, and the dashed lines are the same p10/p90 band "
            "as above. This is the only part of the page that tells you whether the forecast above "
            "is worth anything on this symbol.",
        )
    ]

    verdict = (
        f"The forecast was off by {_num(mape, 2, '%')} on average, against {_num(naive, 2, '%')} "
        "for simply assuming the price never changed. "
    )
    verdict += (
        "The model beat that baseline here, which is the minimum bar for taking it seriously."
        if beat
        else (
            "The model lost to that baseline here, so the forecast above is not adding information "
            "on this symbol and configuration. Try a shorter lookback before reading anything into "
            "the direction."
        )
    )
    out.append(_para("Did it beat doing nothing?", verdict))

    hit = backtest.get("directional_hit_rate_pct")
    if hit is not None:
        if hit >= 60:
            hit_note = "better than a coin flip on this sample, though the sample is tiny."
        elif hit <= 40:
            hit_note = "worse than a coin flip — the per-bar direction was more often wrong than right."
        else:
            hit_note = "indistinguishable from a coin flip at this sample size."
        out.append(
            _para(
                "Direction, bar by bar",
                f"It called the direction of {_num(hit, 0, '%')} of individual bars, {hit_note} "
                f"The end-of-window direction was "
                f"{'correct' if backtest.get('terminal_direction_correct') else 'wrong'}.",
            )
        )

    coverage = backtest.get("band_coverage_pct")
    if coverage is not None:
        if coverage < TARGET_COVERAGE - COVERAGE_SLACK:
            note = (
                "well under the ~80% a p10–p90 band should contain, so the band was too narrow — "
                "the model was more confident than it had any right to be."
            )
        elif coverage > TARGET_COVERAGE + COVERAGE_SLACK:
            note = (
                "above the ~80% a p10–p90 band should contain. The band was wide enough to be "
                "almost always right, which also makes it almost useless for deciding anything."
            )
        else:
            note = "close to the ~80% a p10–p90 band should contain, so the uncertainty was honest."
        out.append(
            _para(
                "Was the uncertainty honest?",
                f"Reality fell inside the band on {_num(coverage, 0, '%')} of the hidden bars — {note}",
            )
        )

    return out


def explain(result: dict) -> dict:
    """Assemble every explanation for one analysis response."""
    return {
        "forecast": explain_forecast(
            result["stats"],
            result["forecast"]["band"],
            result["params"],
            result["interval_label"],
            result.get("technicals"),
        ),
        "backtest": explain_backtest(result.get("backtest")),
    }
