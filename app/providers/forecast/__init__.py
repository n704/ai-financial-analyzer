"""Forecast providers (F6): the naive baselines exposed as a provider (P6.4),
a deterministic fake for tests, and the TimesFM adapter (P6.5). Only
``timesfm.py`` imports ``timesfm``/``torch``/``numpy`` — and lazily, so the
package imports cleanly with the ``forecast`` extra absent.
"""
