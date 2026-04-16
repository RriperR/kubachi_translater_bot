"""Добавить счётчики профиля пользователя и заполнить их из текущих данных."""

from __future__ import annotations

from alembic import op

revision = "20260416_0011"
down_revision = "20260416_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить денормализованные счётчики в users и заполнить их из журнала и контента."""
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS searches_count INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS suggestions_count INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS comments_count INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS user_entries_count INTEGER NOT NULL DEFAULT 0
        """
    )

    op.execute(
        """
        UPDATE users
        SET
            searches_count = 0,
            suggestions_count = 0,
            comments_count = 0,
            user_entries_count = 0
        """
    )

    op.execute(
        """
        UPDATE users
        SET searches_count = search_stats.searches_count
        FROM (
            SELECT fk_user, COUNT(*)::INTEGER AS searches_count
            FROM actions
            WHERE action_type IN ('search', 'not_found')
            GROUP BY fk_user
        ) AS search_stats
        WHERE users.id = search_stats.fk_user
        """
    )
    op.execute(
        """
        UPDATE users
        SET suggestions_count = suggestion_stats.suggestions_count
        FROM (
            SELECT fk_user, COUNT(*)::INTEGER AS suggestions_count
            FROM suggestions
            GROUP BY fk_user
        ) AS suggestion_stats
        WHERE users.id = suggestion_stats.fk_user
        """
    )
    op.execute(
        """
        UPDATE users
        SET comments_count = comment_stats.comments_count
        FROM (
            SELECT user_id, COUNT(*)::INTEGER AS comments_count
            FROM dictionary_entry_comments
            WHERE user_id IS NOT NULL
            GROUP BY user_id
        ) AS comment_stats
        WHERE users.id = comment_stats.user_id
        """
    )
    op.execute(
        """
        UPDATE users
        SET user_entries_count = entry_stats.user_entries_count
        FROM (
            SELECT user_id, COUNT(*)::INTEGER AS user_entries_count
            FROM dictionary_entries
            WHERE source = 'user'
              AND user_id IS NOT NULL
            GROUP BY user_id
        ) AS entry_stats
        WHERE users.id = entry_stats.user_id
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_actions_fk_user
        ON actions(fk_user)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_actions_fk_user_action_type
        ON actions(fk_user, action_type)
        """
    )


def downgrade() -> None:
    """Удалить денормализованные счётчики профиля пользователя."""
    op.execute("DROP INDEX IF EXISTS idx_actions_fk_user_action_type")
    op.execute("DROP INDEX IF EXISTS idx_actions_fk_user")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS user_entries_count")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS comments_count")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS suggestions_count")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS searches_count")
