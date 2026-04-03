"""Удалить legacy-колонки из dictionary_entries."""

from __future__ import annotations

from alembic import op

revision = "20260403_0007"
down_revision = "20260403_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Удалить больше неиспользуемые поля-кэши из dictionary_entries."""
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS examples")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS notes")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS comments")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS contributor_username")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS contributor_first_name")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS contributor_last_name")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS banner")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS normalized_comments")
    op.execute("ALTER TABLE dictionary_entries DROP COLUMN IF EXISTS normalized_search_text")


def downgrade() -> None:
    """Вернуть legacy-колонки dictionary_entries для отката миграции."""
    op.execute("ALTER TABLE dictionary_entries ADD COLUMN IF NOT EXISTS examples TEXT[]")
    op.execute("ALTER TABLE dictionary_entries ADD COLUMN IF NOT EXISTS notes TEXT[]")
    op.execute(
        "ALTER TABLE dictionary_entries ADD COLUMN IF NOT EXISTS comments TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE dictionary_entries ADD COLUMN IF NOT EXISTS contributor_username TEXT"
    )
    op.execute(
        "ALTER TABLE dictionary_entries ADD COLUMN IF NOT EXISTS contributor_first_name TEXT"
    )
    op.execute(
        "ALTER TABLE dictionary_entries ADD COLUMN IF NOT EXISTS contributor_last_name TEXT"
    )
    op.execute("ALTER TABLE dictionary_entries ADD COLUMN IF NOT EXISTS banner TEXT")
    op.execute(
        "ALTER TABLE dictionary_entries "
        "ADD COLUMN IF NOT EXISTS normalized_comments TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE dictionary_entries "
        "ADD COLUMN IF NOT EXISTS normalized_search_text TEXT NOT NULL DEFAULT ''"
    )
