"""Удалить legacy-колонку date_time из actions."""

from __future__ import annotations

from alembic import op

revision = "20260416_0009"
down_revision = "20260403_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Удалить больше не используемую строковую колонку локального времени."""
    op.execute("ALTER TABLE actions DROP COLUMN IF EXISTS date_time")


def downgrade() -> None:
    """Вернуть legacy-колонку date_time и заполнить её из created_at."""
    op.execute("ALTER TABLE actions ADD COLUMN IF NOT EXISTS date_time TEXT")
    op.execute(
        """
        UPDATE actions
        SET date_time = TO_CHAR(
            (COALESCE(created_at, NOW()) AT TIME ZONE 'UTC') + INTERVAL '3 hours',
            'YYYY-MM-DD HH24:MI:SS'
        )
        WHERE date_time IS NULL
        """
    )
    op.execute("ALTER TABLE actions ALTER COLUMN date_time SET NOT NULL")
