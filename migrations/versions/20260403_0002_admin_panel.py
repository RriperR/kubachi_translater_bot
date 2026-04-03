"""Схема данных для admin panel и предложений пользователей."""

from __future__ import annotations

from alembic import op

revision = "20260403_0002"
down_revision = "20260402_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить таблицу suggestions и временные метки для админских отчетов."""
    op.execute(
        r"""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        UPDATE users AS users_table
        SET created_at = COALESCE(
                (
                    SELECT MIN(actions.date_time::timestamp)
                    FROM actions
                    WHERE actions.fk_user = users_table.id
                ),
                NOW()
            ),
            updated_at = COALESCE(
                (
                    SELECT MAX(actions.date_time::timestamp)
                    FROM actions
                    WHERE actions.fk_user = users_table.id
                ),
                COALESCE(
                    (
                        SELECT MIN(actions.date_time::timestamp)
                        FROM actions
                        WHERE actions.fk_user = users_table.id
                    ),
                    NOW()
                )
            )
        WHERE users_table.id IN (
            SELECT DISTINCT fk_user
            FROM actions
        )
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
        ALTER TABLE actions
        ALTER COLUMN created_at SET DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        ALTER TABLE actions
        ALTER COLUMN created_at SET NOT NULL
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
        UPDATE dictionary_entries AS entries
        SET created_at = COALESCE(
                contributors.created_at,
                (
                    SELECT MIN(comments.created_at)
                    FROM dictionary_entry_comments AS comments
                    WHERE comments.entry_id = entries.id
                ),
                NOW()
            ),
            updated_at = COALESCE(
                (
                    SELECT MAX(comments.created_at)
                    FROM dictionary_entry_comments AS comments
                    WHERE comments.entry_id = entries.id
                ),
                contributors.updated_at,
                contributors.created_at,
                NOW()
            )
        FROM dictionary_contributors AS contributors
        WHERE contributors.id = entries.contributor_id
        """
    )
    op.execute(
        r"""
        UPDATE dictionary_entries AS entries
        SET created_at = COALESCE(
                created_at,
                (
                    SELECT MIN(comments.created_at)
                    FROM dictionary_entry_comments AS comments
                    WHERE comments.entry_id = entries.id
                ),
                NOW()
            ),
            updated_at = COALESCE(
                updated_at,
                (
                    SELECT MAX(comments.created_at)
                    FROM dictionary_entry_comments AS comments
                    WHERE comments.entry_id = entries.id
                ),
                created_at,
                NOW()
            )
        """
    )
    op.execute(
        r"""
        ALTER TABLE dictionary_entries
        ALTER COLUMN created_at SET DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        ALTER TABLE dictionary_entries
        ALTER COLUMN updated_at SET DEFAULT NOW()
        """
    )
    op.execute(
        r"""
        ALTER TABLE dictionary_entries
        ALTER COLUMN created_at SET NOT NULL
        """
    )
    op.execute(
        r"""
        ALTER TABLE dictionary_entries
        ALTER COLUMN updated_at SET NOT NULL
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
        CREATE TABLE IF NOT EXISTS suggestions (
            id BIGSERIAL PRIMARY KEY,
            fk_user BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
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
    """Удалить схему admin panel."""
    op.execute("DROP INDEX IF EXISTS idx_suggestions_status")
    op.execute("DROP INDEX IF EXISTS idx_suggestions_fk_user")
    op.execute("DROP INDEX IF EXISTS idx_suggestions_updated_at")
    op.execute("DROP INDEX IF EXISTS idx_suggestions_created_at")
    op.execute("DROP TABLE IF EXISTS suggestions")
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
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS created_at")
