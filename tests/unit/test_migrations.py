"""P1.8: Alembic upgrade/downgrade cycles clean on SQLite.

Postgres is exercised in CI via the testcontainers integration job (added
alongside this DB layer); it isn't run here since it needs a live Postgres.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def _alembic_config(db_url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "app" / "db" / "migrations"))
    cfg.cmd_opts = type("Opts", (), {"x": [f"db_url={db_url}"]})()  # type: ignore[attr-defined]
    return cfg


def test_upgrade_head_then_downgrade_base_clean(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate_test.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(db_url)

    command.upgrade(cfg, "head")
    assert db_path.exists()

    command.downgrade(cfg, "base")
    # After downgrading to base, only alembic's own bookkeeping table remains.
    import sqlite3

    con = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    finally:
        con.close()
    assert tables == {"alembic_version"}
