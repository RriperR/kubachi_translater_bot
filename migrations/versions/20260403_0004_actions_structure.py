"""Нормализовать журнал действий и вынести типы поиска в отдельные поля."""

from __future__ import annotations

from alembic import op

revision = "20260403_0004"
down_revision = "20260403_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить структурированные поля в actions и разобрать старые search-записи."""
    op.execute(
        r"""
        ALTER TABLE actions
        ADD COLUMN IF NOT EXISTS action_type TEXT NOT NULL DEFAULT 'generic'
        """
    )
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
        SET action_type = 'search',
            action_query = regexp_replace(action, '^SEARCH:\s*', ''),
            search_found = TRUE,
            action = regexp_replace(action, '^SEARCH:\s*', '')
        WHERE action LIKE 'SEARCH:%'
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action_type = 'search',
            action_query = regexp_replace(action, '^NOTFOUND:\s*', ''),
            search_found = FALSE,
            action = regexp_replace(action, '^NOTFOUND:\s*', '')
        WHERE action LIKE 'NOTFOUND:%'
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action_type = 'command'
        WHERE action_type = 'generic'
          AND action LIKE '/%'
        """
    )

    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_actions_action_type
        ON actions(action_type)
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


def downgrade() -> None:
    """Откатить структурированные поля actions."""
    op.execute("DROP INDEX IF EXISTS idx_actions_action_query")
    op.execute("DROP INDEX IF EXISTS idx_actions_search_found")
    op.execute("DROP INDEX IF EXISTS idx_actions_action_type")
    op.execute("ALTER TABLE actions DROP COLUMN IF EXISTS search_found")
    op.execute("ALTER TABLE actions DROP COLUMN IF EXISTS action_query")
    op.execute("ALTER TABLE actions DROP COLUMN IF EXISTS action_type")
