"""Добавить таблицы для сохранения задач рассылки и статусов доставки."""

from __future__ import annotations

from alembic import op

revision = "20260417_0012"
down_revision = "20260416_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать таблицы рассылок и детализацию доставки по каждому пользователю."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS broadcasts (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ NULL,
            completed_at TIMESTAMPTZ NULL,
            created_by BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
            audience_type TEXT NOT NULL,
            audience_days INTEGER NULL,
            source_chat_id BIGINT NOT NULL,
            source_message_id BIGINT NOT NULL,
            text_preview TEXT NOT NULL DEFAULT '',
            content_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            total_recipients INTEGER NOT NULL DEFAULT 0,
            sent_count INTEGER NOT NULL DEFAULT 0,
            blocked_count INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_broadcasts_created_at
        ON broadcasts(created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_broadcasts_status
        ON broadcasts(status)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_broadcasts_created_by
        ON broadcasts(created_by)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS broadcast_deliveries (
            id BIGSERIAL PRIMARY KEY,
            broadcast_id BIGINT NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
            user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
            chat_id BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NULL,
            telegram_message_id BIGINT NULL,
            sent_at TIMESTAMPTZ NULL,
            last_attempt_at TIMESTAMPTZ NULL,
            next_retry_at TIMESTAMPTZ NULL,
            UNIQUE (broadcast_id, chat_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_broadcast_deliveries_broadcast_id
        ON broadcast_deliveries(broadcast_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_broadcast_deliveries_broadcast_status
        ON broadcast_deliveries(broadcast_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_broadcast_deliveries_user_id
        ON broadcast_deliveries(user_id)
        """
    )


def downgrade() -> None:
    """Удалить таблицы рассылок и детализацию доставки."""
    op.execute("DROP INDEX IF EXISTS idx_broadcast_deliveries_user_id")
    op.execute("DROP INDEX IF EXISTS idx_broadcast_deliveries_broadcast_status")
    op.execute("DROP INDEX IF EXISTS idx_broadcast_deliveries_broadcast_id")
    op.execute("DROP TABLE IF EXISTS broadcast_deliveries")
    op.execute("DROP INDEX IF EXISTS idx_broadcasts_created_by")
    op.execute("DROP INDEX IF EXISTS idx_broadcasts_status")
    op.execute("DROP INDEX IF EXISTS idx_broadcasts_created_at")
    op.execute("DROP TABLE IF EXISTS broadcasts")
