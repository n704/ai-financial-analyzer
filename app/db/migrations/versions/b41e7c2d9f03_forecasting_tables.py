"""forecasting tables (P6.2 / P6.6)

Revision ID: b41e7c2d9f03
Revises: 727d8aab64c3
Create Date: 2026-09-02 21:30:00.000000

Adds ``price_series`` (the global, non-user-scoped bar cache) and ``forecasts``
(user-owned forecast artifacts). Touches no existing table (PLAN.md: P6 makes
"no schema changes to existing tables").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b41e7c2d9f03"
down_revision: str | Sequence[str] | None = "727d8aab64c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "price_series",
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("interval", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("bars", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("ticker", "interval", "source", "as_of"),
    )
    op.create_table(
        "forecasts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("interval", sa.String(length=10), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("transform", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("checkpoint_revision", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("context_start", sa.Date(), nullable=True),
        sa.Column("context_end", sa.Date(), nullable=True),
        sa.Column("context_length", sa.Integer(), nullable=True),
        sa.Column("point", sa.JSON(), nullable=True),
        sa.Column("quantile_levels", sa.JSON(), nullable=True),
        sa.Column("quantiles", sa.JSON(), nullable=True),
        sa.Column("band_source", sa.String(length=20), nullable=True),
        sa.Column("backtest", sa.JSON(), nullable=True),
        sa.Column("skill", sa.String(length=30), nullable=True),
        sa.Column("skill_score", sa.Float(), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("disclaimer_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "input_hash", name="uq_forecasts_user_input_hash"),
    )
    op.create_index(op.f("ix_forecasts_user_id"), "forecasts", ["user_id"], unique=False)
    op.create_index(op.f("ix_forecasts_document_id"), "forecasts", ["document_id"], unique=False)
    op.create_index(op.f("ix_forecasts_ticker"), "forecasts", ["ticker"], unique=False)
    op.create_index("ix_forecasts_user_created", "forecasts", ["user_id", "created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_forecasts_user_created", table_name="forecasts")
    op.drop_index(op.f("ix_forecasts_ticker"), table_name="forecasts")
    op.drop_index(op.f("ix_forecasts_document_id"), table_name="forecasts")
    op.drop_index(op.f("ix_forecasts_user_id"), table_name="forecasts")
    op.drop_table("forecasts")
    op.drop_table("price_series")
