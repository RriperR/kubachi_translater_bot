"""Пересчитать users.updated_at по последнему действию пользователя."""

from __future__ import annotations

from alembic import op

revision = "20260416_0010"
down_revision = "20260416_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Обновить updated_at у пользователей по максимальному created_at из actions."""
    op.execute(
        """
        UPDATE users AS users_table
        SET updated_at = latest_actions.last_action_at
        FROM (
            SELECT fk_user, MAX(created_at) AS last_action_at
            FROM actions
            GROUP BY fk_user
        ) AS latest_actions
        WHERE users_table.id = latest_actions.fk_user
          AND users_table.updated_at IS DISTINCT FROM latest_actions.last_action_at
        """
    )


def downgrade() -> None:
    """Откат не нужен: обновление updated_at вычисляется из уже существующих действий."""
