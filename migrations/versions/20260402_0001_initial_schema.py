"""Первичная схема приложения для Alembic."""

from __future__ import annotations

from alembic import op

revision = "20260402_0001"
down_revision = None
branch_labels = None
depends_on = None

VECTOR_DIMENSIONS = 384


def upgrade() -> None:
    """Создать все таблицы и индексы текущей схемы приложения."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        r"""
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            username TEXT,
            firstname TEXT NOT NULL,
            lastname TEXT NOT NULL,
            chatid TEXT NOT NULL UNIQUE,
            mode TEXT NOT NULL DEFAULT 'lite'
        )
        """
    )
    op.execute(
        r"""
        CREATE TABLE IF NOT EXISTS actions (
            id BIGSERIAL PRIMARY KEY,
            action TEXT NOT NULL,
            date_time TEXT NOT NULL,
            fk_user BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        r"""
        CREATE TABLE IF NOT EXISTS dictionary_entries (
            id BIGSERIAL PRIMARY KEY,
            source TEXT NOT NULL CHECK (source IN ('core', 'user')),
            word TEXT NOT NULL,
            translation TEXT NOT NULL,
            normalized_word TEXT NOT NULL DEFAULT '',
            normalized_translation TEXT NOT NULL DEFAULT '',
            contributor_id BIGINT,
            UNIQUE (source, word, translation)
        )
        """
    )
    op.execute(
        r"""
        ALTER TABLE dictionary_entries
        ADD COLUMN IF NOT EXISTS contributor_id BIGINT
        """
    )
    op.execute(
        r"""
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
        r"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_dictionary_contributors_chat_id
        ON dictionary_contributors(chat_id)
        WHERE chat_id IS NOT NULL
        """
    )
    op.execute(
        r"""
        CREATE TABLE IF NOT EXISTS dictionary_entry_examples (
            id BIGSERIAL PRIMARY KEY,
            entry_id BIGINT NOT NULL
                REFERENCES dictionary_entries(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            text TEXT NOT NULL,
            normalized_text TEXT NOT NULL DEFAULT '',
            UNIQUE (entry_id, position)
        )
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entry_examples_entry
        ON dictionary_entry_examples(entry_id)
        """
    )
    op.execute(
        r"""
        CREATE TABLE IF NOT EXISTS dictionary_entry_notes (
            id BIGSERIAL PRIMARY KEY,
            entry_id BIGINT NOT NULL
                REFERENCES dictionary_entries(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            text TEXT NOT NULL,
            normalized_text TEXT NOT NULL DEFAULT '',
            UNIQUE (entry_id, position)
        )
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entry_notes_entry
        ON dictionary_entry_notes(entry_id)
        """
    )
    op.execute(
        r"""
        CREATE TABLE IF NOT EXISTS dictionary_entry_comments (
            id BIGSERIAL PRIMARY KEY,
            entry_id BIGINT NOT NULL
                REFERENCES dictionary_entries(id) ON DELETE CASCADE,
            contributor_id BIGINT REFERENCES dictionary_contributors(id)
                ON DELETE SET NULL,
            text TEXT NOT NULL,
            normalized_text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entry_comments_entry
        ON dictionary_entry_comments(entry_id)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entry_comments_contributor
        ON dictionary_entry_comments(contributor_id)
        """
    )
    op.execute(
        r"""
        ALTER TABLE dictionary_entries
        ADD COLUMN IF NOT EXISTS normalized_word TEXT NOT NULL DEFAULT ''
        """
    )
    op.execute(
        r"""
        ALTER TABLE dictionary_entries
        ADD COLUMN IF NOT EXISTS normalized_translation TEXT NOT NULL DEFAULT ''
        """
    )
    op.execute(
        r"""
        UPDATE dictionary_entries
        SET normalized_word = btrim(
                regexp_replace(
                    lower(translate(word, '1!l|I', 'iiiii')),
                    '\s+',
                    ' ',
                    'g'
                )
            ),
            normalized_translation = btrim(
                regexp_replace(
                    regexp_replace(
                        lower(translate(translation, '1!l|I', 'iiiii')),
                        '[(){}\[\],.;:!?\"''«»]+',
                        ' ',
                        'g'
                    ),
                    '\s+',
                    ' ',
                    'g'
                )
            )
        WHERE normalized_word = ''
           OR normalized_translation = ''
           OR normalized_translation ~ '[(){}\[\],.;:!?\"''«»]'
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entries_source
        ON dictionary_entries(source)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entries_normalized_word
        ON dictionary_entries(source, normalized_word)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entries_normalized_translation
        ON dictionary_entries(source, normalized_translation)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entries_contributor
        ON dictionary_entries(contributor_id)
        """
    )
    op.execute(
        r"""
        CREATE TABLE IF NOT EXISTS dictionary_entry_chunks (
            id BIGSERIAL PRIMARY KEY,
            entry_id BIGINT NOT NULL
                REFERENCES dictionary_entries(id) ON DELETE CASCADE,
            source TEXT NOT NULL CHECK (source IN ('core', 'user')),
            chunk_type TEXT NOT NULL CHECK (
                chunk_type IN ('title', 'translation', 'example', 'note', 'comment')
            ),
            source_row_id BIGINT,
            chunk_order INTEGER NOT NULL DEFAULT 0,
            chunk_text TEXT NOT NULL,
            normalized_chunk_text TEXT NOT NULL DEFAULT '',
            UNIQUE (entry_id, chunk_type, chunk_order)
        )
        """
    )
    op.execute(
        r"""
        ALTER TABLE dictionary_entry_chunks
        ADD COLUMN IF NOT EXISTS source_row_id BIGINT
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entry_chunks_entry
        ON dictionary_entry_chunks(entry_id)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entry_chunks_source_type
        ON dictionary_entry_chunks(source, chunk_type)
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_entry_chunks_search_vector
        ON dictionary_entry_chunks
        USING GIN (to_tsvector('simple', normalized_chunk_text))
        """
    )
    op.execute(
        fr"""
        CREATE TABLE IF NOT EXISTS dictionary_chunk_embeddings (
            chunk_id BIGINT PRIMARY KEY
                REFERENCES dictionary_entry_chunks(id) ON DELETE CASCADE,
            embedding_provider TEXT,
            embedding_model TEXT,
            embedding_version TEXT NOT NULL DEFAULT '',
            vector_dimensions INTEGER,
            embedding_status TEXT NOT NULL DEFAULT 'pending' CHECK (
                embedding_status IN ('pending', 'ready', 'error')
            ),
            embedding vector({VECTOR_DIMENSIONS}),
            content_hash TEXT NOT NULL DEFAULT '',
            last_indexed_at TIMESTAMPTZ,
            last_error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    op.execute(
        r"""
        CREATE INDEX IF NOT EXISTS idx_dictionary_chunk_embeddings_hnsw
        ON dictionary_chunk_embeddings
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    """Удалить текущую схему приложения."""
    op.execute("DROP INDEX IF EXISTS idx_dictionary_chunk_embeddings_hnsw")
    op.execute("DROP TABLE IF EXISTS dictionary_chunk_embeddings")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entry_chunks_search_vector")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entry_chunks_source_type")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entry_chunks_entry")
    op.execute("DROP TABLE IF EXISTS dictionary_entry_chunks")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entries_contributor")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entries_normalized_translation")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entries_normalized_word")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_entries_source")
    op.execute("DROP TABLE IF EXISTS dictionary_entry_comments")
    op.execute("DROP TABLE IF EXISTS dictionary_entry_notes")
    op.execute("DROP TABLE IF EXISTS dictionary_entry_examples")
    op.execute("DROP INDEX IF EXISTS idx_dictionary_contributors_chat_id")
    op.execute("DROP TABLE IF EXISTS dictionary_contributors")
    op.execute("DROP TABLE IF EXISTS dictionary_entries")
    op.execute("DROP TABLE IF EXISTS actions")
    op.execute("DROP TABLE IF EXISTS users")
