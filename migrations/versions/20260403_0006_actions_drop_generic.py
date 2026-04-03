"""Убрать generic из журнала действий и нормализовать старые записи."""

from __future__ import annotations

from alembic import op

revision = "20260403_0006"
down_revision = "20260403_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Перевести generic-записи в command/search и убрать кавычки у старых запросов."""
    op.execute(
        r"""
        UPDATE actions
        SET action = regexp_replace(action, '^"(.*)"$', '\1')
        WHERE action ~ '^".*"$'
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action = '/suggest sent'
        WHERE action = 'SUGGEST'
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action = '/add saved: ' || regexp_replace(action, '^ADD\s+"?(.*)"?$', '\1')
        WHERE action ~ '^ADD\s+'
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action_type = CASE
            WHEN action LIKE '/%' THEN 'command'
            ELSE 'search'
        END
        WHERE action_type = 'generic'
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action_type = 'command'
        WHERE action_type NOT IN ('command', 'search', 'not_found')
          AND action LIKE '/%'
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action_type = 'search'
        WHERE action_type NOT IN ('command', 'search', 'not_found')
        """
    )


def downgrade() -> None:
    """Вернуть generic для записей, которые были автоматически переклассифицированы."""
    op.execute(
        r"""
        UPDATE actions
        SET action_type = 'generic'
        WHERE action_type = 'search'
          AND action NOT LIKE '/%'
        """
    )
    op.execute(
        r"""
        UPDATE actions
        SET action_type = 'generic'
        WHERE action_type = 'command'
          AND action IN ('/suggest sent')
        """
    )
