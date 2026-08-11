/**
 * One definition per term, used everywhere that term appears.
 *
 * Keeping them here rather than inline means "conviction" is explained the same
 * way in the risk panel, the compare table and the chart legend — and that
 * fixing a definition fixes it in every place at once.
 */
export const GLOSSARY = {
  p10_p90:
    'The 10th and 90th percentiles of the sampled futures. Roughly 8 in 10 of the model’s own paths finish inside this band — it is the model’s uncertainty, not a guarantee.',
  median_path:
    'The middle of the sampled futures at each step (p50). Half the paths are above it and half below. It is not the "most likely" price, just the centre of the distribution.',
  sampled_paths:
    'Each faint line is one complete future the model drew. They are samples from one distribution, not independent opinions, so agreement between them is not confirmation.',
  prob_up:
    'The share of sampled futures ending above today’s close. It describes this model on this price history only — no earnings, news or fundamentals are involved.',
  conviction:
    'Mean forecast return divided by the spread across paths (μ/σ). High means the paths agree; near zero means the average move is small next to the disagreement, which is noise.',
  dispersion:
    'One standard deviation of the terminal returns across paths — how far apart the sampled futures ended up.',
  var_5:
    'Value at risk: the 5th-percentile return. One in twenty sampled futures did at least this badly.',
  expected_shortfall:
    'The average return across the worst 5% of sampled futures — how bad it gets when it goes bad, rather than just the cutoff.',
  max_drawdown:
    'The largest peak-to-trough fall along the median path over the horizon.',
  forecast_vol:
    'Annualised volatility implied by the step-to-step moves of the sampled paths.',
  realized_vol:
    'Annualised volatility of the stock’s actual past returns over the downloaded history.',
  mape: 'Mean absolute percentage error of the forecast median against what actually happened on the withheld bars. Lower is better.',
  naive_baseline:
    'The error you would get by assuming the price simply never changes. A forecast that cannot beat this is not adding information.',
  band_coverage:
    'How often reality landed inside the p10–p90 band on the withheld bars. It should be near 80%: far below means the band was too confident, far above means it was too wide to be useful.',
  directional_hit:
    'The share of individual bars where the forecast got the direction of the move right. 50% is a coin flip.',
  rsi: 'Relative Strength Index over 14 bars. Above 70 is conventionally "overbought", below 30 "oversold" — a description of recent momentum, not a prediction.',
  sma: 'Simple moving average of the closing price over the given number of bars.',
}

export const define = (key) => GLOSSARY[key] ?? null
