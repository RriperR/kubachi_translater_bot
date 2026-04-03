"""Довести существующую БД до схемы admin panel."""

from __future__ import annotations

from alembic import op

revision = "20260403_0003"
down_revision = "20260403_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Дотянуть поля и индексы для админки на уже существующей базе."""
    op.execute(
        r"""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        UPDATE users AS users_table
        SET updated_at = COALESCE(
                (
                    SELECT MAX(COALESCE(actions.created_at, actions.date_time::timestamp))
                    FROM actions
                    WHERE actions.fk_user = users_table.id
                ),
                created_at,
                NOW()
            )
        WHERE users_table.updated_at IS NULL
           OR users_table.updated_at = users_table.created_at
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_users_created_at
        ON users(created_at)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_users_updated_at
        ON users(updated_at)
        """
    )

    op.execute(
        r"""
        ALTER TABLE actions
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET created_at = COALESCE(created_at, date_time::timestamp, NOW())
        WHERE created_at IS NULL
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_actions_created_at
        ON actions(created_at)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_actions_action
        ON actions(action)
        """
    )

    op.execute(
        r"""
        ALTER TABLE dictionary_entries
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        ALTER TABLE dictionary_entries
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        UPDATE dictionary_entries
        SET created_at = COALESCE(created_at, NOW()),
            updated_at = COALESCE(updated_at, created_at, NOW())
        WHERE created_at IS NULL
           OR updated_at IS NULL
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entries_created_at
        ON dictionary_entries(created_at)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entries_updated_at
        ON dictionary_entries(updated_at)
        """
    )

    op.execute(
        r"""
        ALTER TABLE suggestions
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        UPDATE suggestions
        SET updated_at = COALESCE(updated_at, created_at, NOW())
        WHERE updated_at IS NULL
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_suggestions_created_at
        ON suggestions(created_at)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_suggestions_updated_at
        ON suggestions(updated_at)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_suggestions_fk_user
        ON suggestions(fk_user)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_suggestions_status
        ON suggestions(status)
        """
    )


def downgrade() -> None:
    """Откатить дополнительные поля admin panel."""
    op.execute("DROP INDEX IF EXISTS idx_suggestions_status")
    op.execute("DROP INDEX IF EXISTS idx_suggestions_fk_user")
    op.execute("DROP INDEX IF EXISTS idx_suggestions_updated_at")
    op.execute("DROP INDEX IF EXISTS idx_suggestions_created_at")
    op.execute("ALTER TABLE suggestions DROP COLUMN IF EXISTS updated_at")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entries_updated_at")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entries_created_at")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS created_at")
    op.execute("DROP INDEX IF EXISTS idx_actions_action")
    op.execute("DROP INDEX IF EXISTS idx_actions_created_at")
    op.execute("ALTER TABLE actions DROP COLUMN IF EXISTS created_at")
    op.execute("DROP INDEX IF EXISTS idx_users_updated_at")
    op.execute("DROP INDEX IF EXISTS idx_users_created_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS updated_at")
