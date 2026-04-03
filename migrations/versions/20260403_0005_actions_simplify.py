"""Упростить журнал действий до action и action_type без отдельных search-полей."""

from __future__ import annotations

from alembic import op

revision = "20260403_0005"
down_revision = "20260403_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Перевести search-статусы в action_type и удалить лишние колонки."""
    op.execute(
        r"""
        UPDATE actions
        SET action_type = 'not_found'
        WHERE action_type = 'search'
          AND search_found IS FALSE
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action_type = 'search'
        WHERE action_type = 'search'
          AND search_found IS NOT FALSE
        """
    )

    op.execute("DROP INDEX IF EXISTS idx_actions_action_query")
    op.execute("DROP INDEX IF EXISTS idx_actions_search_found")
    op.execute("ALTER TABLE actions DROP COLUMN IF EXISTS action_query")
    op.execute("ALTER TABLE actions DROP COLUMN IF EXISTS search_found")

    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_actions_action_type
        ON actions(action_type)
        """
    )


def downgrade() -> None:
    """Вернуть отдельные search-поля в actions."""
    op.execute(
        r"""
        ALTER TABLE actions
        ADD COLUMN IF NOT EXISTS action_query TEXT
        """
    )
    op.execute(
        r"""
        ALTER TABLE actions
        ADD COLUMN IF NOT EXISTS search_found BOOLEAN
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action_query = action,
            search_found = TRUE
        WHERE action_type = 'search'
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action_query = action,
            search_found = FALSE,
            action_type = 'search'
        WHERE action_type = 'not_found'
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_actions_search_found
        ON actions(search_found)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_actions_action_query
        ON actions(action_query)
        """
    )
