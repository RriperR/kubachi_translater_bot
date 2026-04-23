"""Добавить публичные настройки имени для таблицы лучших."""

from __future__ import annotations

from alembic import op

revision = "20260423_0014"
down_revision = "20260417_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить настройки отображения пользователя в рейтингах."""
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS score_name_policy TEXT NOT NULL DEFAULT 'anonymous'
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS score_custom_name TEXT NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'users_score_name_policy_check'
            ) THEN
                ALTER TABLE users
                ADD CONSTRAINT users_score_name_policy_check
                CHECK (score_name_policy IN ('anonymous', 'telegram', 'custom'));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Удалить настройки отображения пользователя в рейтингах."""
    op.execute(
        """
        ALTER TABLE users
        DROP CONSTRAINT IF EXISTS users_score_name_policy_check
        """
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS score_custom_name")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS score_name_policy")
