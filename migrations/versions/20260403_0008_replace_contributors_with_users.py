"""Заменить dictionary_contributors на прямые связи со users."""

from __future__ import annotations

from alembic import op

revision = "20260403_0008"
down_revision = "20260403_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Переложить авторов статей и комментариев на прямые FK к users."""
    op.execute(
        """
        ALTER TABLE dictionary_entries
        ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE dictionary_entry_comments
        ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        WITH resolved_users AS (
            SELECT
                entries.id AS entry_id,
                COALESCE(chat_users.id, named_users.id) AS user_id
            FROM dictionary_entries AS entries
            JOIN dictionary_contributors AS contributors
                ON contributors.id = entries.contributor_id
            LEFT JOIN users AS chat_users
                ON contributors.chat_id IS NOT NULL
               AND chat_users.chatid = contributors.chat_id::text
            LEFT JOIN users AS named_users
                ON chat_users.id IS NULL
               AND named_users.username IS NOT DISTINCT FROM contributors.username
               AND named_users.firstname = contributors.first_name
               AND named_users.lastname = contributors.last_name
        )
        UPDATE dictionary_entries AS entries
        SET user_id = resolved_users.user_id
        FROM resolved_users
        WHERE entries.id = resolved_users.entry_id
          AND resolved_users.user_id IS NOT NULL
          AND entries.user_id IS NULL
        """
    )
    op.execute(
        """
        WITH resolved_users AS (
            SELECT
                comments.id AS comment_id,
                COALESCE(chat_users.id, named_users.id) AS user_id
            FROM dictionary_entry_comments AS comments
            JOIN dictionary_contributors AS contributors
                ON contributors.id = comments.contributor_id
            LEFT JOIN users AS chat_users
                ON contributors.chat_id IS NOT NULL
               AND chat_users.chatid = contributors.chat_id::text
            LEFT JOIN users AS named_users
                ON chat_users.id IS NULL
               AND named_users.username IS NOT DISTINCT FROM contributors.username
               AND named_users.firstname = contributors.first_name
               AND named_users.lastname = contributors.last_name
        )
        UPDATE dictionary_entry_comments AS comments
        SET user_id = resolved_users.user_id
        FROM resolved_users
        WHERE comments.id = resolved_users.comment_id
          AND resolved_users.user_id IS NOT NULL
          AND comments.user_id IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dictionary_entries_user
        ON dictionary_entries(user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dictionary_entry_comments_user
        ON dictionary_entry_comments(user_id)
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entries_contributor")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entry_comments_contributor")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS contributor_id")
    op.execute("ALTER TABLE dictionary_entry_comments DROP COLUMN IF EXISTS contributor_id")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_contributors_chat_id")
    op.execute("DROP TABLE IF EXISTS dictionary_contributors")


def downgrade() -> None:
    """Вернуть отдельную таблицу authors и старые contributor_id."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dictionary_contributors (
            id BIGSERIAL PRIMARY KEY,
            chat_id BIGINT,
            username TEXT,
            first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dictionary_contributors_chat_id
        ON dictionary_contributors(chat_id)
        WHERE chat_id IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO dictionary_contributors (
            chat_id,
            username,
            first_name,
            last_name,
            created_at,
            updated_at
        )
        SELECT DISTINCT
            users.chatid::bigint,
            users.username,
            users.firstname,
            users.lastname,
            users.created_at,
            users.updated_at
        FROM users
        WHERE EXISTS (
            SELECT 1 FROM dictionary_entries WHERE dictionary_entries.user_id = users.id
            UNION ALL
            SELECT 1
            FROM dictionary_entry_comments
            WHERE dictionary_entry_comments.user_id = users.id
        )
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        ALTER TABLE dictionary_entries
        ADD COLUMN IF NOT EXISTS contributor_id BIGINT
            REFERENCES dictionary_contributors(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE dictionary_entry_comments
        ADD COLUMN IF NOT EXISTS contributor_id BIGINT
            REFERENCES dictionary_contributors(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        UPDATE dictionary_entries AS entries
        SET contributor_id = contributors.id
        FROM users
        JOIN dictionary_contributors AS contributors
            ON contributors.chat_id = users.chatid::bigint
        WHERE entries.user_id = users.id
        """
    )
    op.execute(
        """
        UPDATE dictionary_entry_comments AS comments
        SET contributor_id = contributors.id
        FROM users
        JOIN dictionary_contributors AS contributors
            ON contributors.chat_id = users.chatid::bigint
        WHERE comments.user_id = users.id
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dictionary_entries_contributor
        ON dictionary_entries(contributor_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dictionary_entry_comments_contributor
        ON dictionary_entry_comments(contributor_id)
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entry_comments_user")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entries_user")
    op.execute("ALTER TABLE dictionary_entry_comments DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS user_id")
