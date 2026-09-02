"""Market-data providers (F6, P6.2): ``fixture`` (hermetic, deterministic —
CI and the offline profile) and ``stooq`` (keyless live EOD bars). Adapters
normalize vendor rows to ``PriceSeries`` and raise only the typed errors in
``app/providers/base.py``; they receive a validated ticker symbol and nothing
else.
"""
