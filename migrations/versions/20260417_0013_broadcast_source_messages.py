"""Добавить хранение списка исходных сообщений для альбомной рассылки."""

from __future__ import annotations

from alembic import op

revision = "20260417_0013"
down_revision = "20260417_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать таблицу с исходными сообщениями рассылки и заполнить её из старого поля."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS broadcast_source_messages (
            id BIGSERIAL PRIMARY KEY,
            broadcast_id BIGINT NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            source_message_id BIGINT NOT NULL,
            UNIQUE (broadcast_id, position),
            UNIQUE (broadcast_id, source_message_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_broadcast_source_messages_broadcast_id
        ON broadcast_source_messages(broadcast_id, position)
        """
    )
    op.execute(
        """
        INSERT INTO broadcast_source_messages (broadcast_id, position, source_message_id)
        SELECT id, 0, source_message_id
        FROM broadcasts
        WHERE source_message_id IS NOT NULL
        ON CONFLICT (broadcast_id, position) DO NOTHING
        """
    )
    op.execute(
        """
        ALTER TABLE broadcasts
        DROP COLUMN IF EXISTS source_message_id
        """
    )


def downgrade() -> None:
    """Вернуть хранение одного source_message_id в таблицу broadcasts."""
    op.execute(
        """
        ALTER TABLE broadcasts
        ADD COLUMN IF NOT EXISTS source_message_id BIGINT NULL
        """
    )
    op.execute(
        """
        UPDATE broadcasts AS broadcasts_table
        SET source_message_id = source_rows.source_message_id
        FROM (
            SELECT DISTINCT ON (broadcast_id)
                broadcast_id,
                source_message_id
            FROM broadcast_source_messages
            ORDER BY broadcast_id, position
        ) AS source_rows
        WHERE broadcasts_table.id = source_rows.broadcast_id
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_broadcast_source_messages_broadcast_id")
    op.execute("DROP TABLE IF EXISTS broadcast_source_messages")
