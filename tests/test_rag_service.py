"""Тесты pgvector-ориентированного retrieval-слоя."""

from __future__ import annotations

import math

from models import (
    DictionaryEntry,
    DictionarySource,
    RagChunkRecord,
    SearchMode,
    SemanticSearchCandidate,
)
from services.rag_service import (
    DictionaryRagIndexer,
    EmbeddingVector,
    HashEmbeddingProvider,
    PgvectorSearchProvider,
)


class SemanticRepositoryStub:
    """Простой репозиторий семантических кандидатов для тестов."""

    def __init__(self, candidates: list[SemanticSearchCandidate]) -> None:
        """Сохранить заранее подготовленных кандидатов.

        Args:
            candidates: Список кандидатов, который будет возвращать репозиторий.
        """
        self._candidates = candidates

    def semantic_search(
        self,
        embedding: str,
        top_k: int,
        provider: str,
        model: str,
        version: str,
        dimensions: int,
    ) -> list[SemanticSearchCandidate]:
        """Вернуть подготовленных семантических кандидатов.

        Args:
            embedding: Сериализованный embedding поискового запроса.
            top_k: Максимальное число возвращаемых кандидатов.
            provider: Имя embedding provider.
            model: Имя embedding-модели.
            version: Версия логики embeddings.
            dimensions: Размерность embeddings.

        Returns:
            Срез заранее подготовленного списка кандидатов.
        """
        assert embedding.startswith("[")
        assert provider == "local"
        assert model == "hash-embedding"
        assert version == "v1"
        assert dimensions == 32
        return self._candidates[:top_k]


class IndexRepositoryStub:
    """Простой репозиторий чанков для тестов индексатора."""

    def __init__(self, chunks: list[RagChunkRecord]) -> None:
        """Сохранить очередь чанков для тестовой индексации.

        Args:
            chunks: Начальный набор pending-чанков.
        """
        self.source = DictionarySource.CORE
        self._chunks = list(chunks)
        self.stored_batches: list[list[tuple[int, str]]] = []
        self.error_batches: list[list[tuple[int, str]]] = []

    def count_pending_rag_chunks(
        self,
        provider: str,
        model: str,
        version: str,
        dimensions: int,
    ) -> int:
        """Вернуть размер очереди pending-чанков.

        Args:
            provider: Имя embedding provider.
            model: Имя embedding-модели.
            version: Версия логики embeddings.
            dimensions: Размерность embeddings.

        Returns:
            Число чанков, еще не выданных индексатору.
        """
        assert provider == "local"
        assert model == "hash-embedding"
        assert version == "v1"
        assert dimensions == 32
        return len(self._chunks)

    def fetch_pending_rag_chunks(
        self,
        limit: int,
        provider: str,
        model: str,
        version: str,
        dimensions: int,
    ) -> list[RagChunkRecord]:
        """Вернуть следующую пачку pending-чанков.

        Args:
            limit: Максимальный размер пакета.
            provider: Имя embedding provider.
            model: Имя embedding-модели.
            version: Версия логики embeddings.
            dimensions: Размерность embeddings.

        Returns:
            Следующая часть очереди чанков.
        """
        assert provider == "local"
        assert model == "hash-embedding"
        assert version == "v1"
        assert dimensions == 32
        batch = self._chunks[:limit]
        self._chunks = self._chunks[limit:]
        return batch

    def store_chunk_embeddings(
        self,
        items: list[tuple[int, str]] | tuple[tuple[int, str], ...],
        provider: str,
        model: str,
        version: str,
        dimensions: int,
    ) -> int:
        """Запомнить пакет embeddings в тестовом хранилище.

        Args:
            items: Пары `(chunk_id, embedding_literal)`.
            provider: Имя провайдера embeddings.
            model: Имя модели embeddings.
            version: Версия логики embeddings.
            dimensions: Размерность embedding-вектора.

        Returns:
            Число сохраненных embeddings.
        """
        assert provider == "local"
        assert model == "hash-embedding"
        assert version == "v1"
        assert dimensions == 32
        stored_items = list(items)
        self.stored_batches.append(stored_items)
        return len(stored_items)

    def mark_chunk_embedding_errors(
        self,
        items: list[tuple[int, str]] | tuple[tuple[int, str], ...],
    ) -> int:
        """Запомнить пакет ошибок индексации.

        Args:
            items: Пары `(chunk_id, error_text)`.

        Returns:
            Число записанных ошибок.
        """
        error_items = list(items)
        self.error_batches.append(error_items)
        return len(error_items)


class FailingEmbeddingProvider(HashEmbeddingProvider):
    """Embedding-провайдер, падающий на определенном тексте."""

    def embed(self, text: str) -> EmbeddingVector:
        """Построить embedding или выбросить тестовую ошибку.

        Args:
            text: Текст чанка для индексации.

        Returns:
            Построенный embedding-вектор.

        Raises:
            ValueError: Если встретился текст, помеченный как ошибочный.
        """
        if text == "broken":
            raise ValueError("boom")
        return super().embed(text)

    def embed_many(self, texts: tuple[str, ...] | list[str]) -> list[EmbeddingVector]:
        """Построить embeddings для набора текстов или выбросить общую ошибку.

        Args:
            texts: Последовательность текстов для пакетной индексации.

        Returns:
            Векторы в исходном порядке.

        Raises:
            ValueError: Если пакет содержит текст `broken`.
        """
        if any(text == "broken" for text in texts):
            raise ValueError("boom")
        return super().embed_many(texts)


def test_hash_embedding_provider_is_deterministic() -> None:
    """Локальный embedder должен стабильно возвращать один и тот же вектор."""
    provider = HashEmbeddingProvider(dimensions=32)

    first = provider.embed("салам привет")
    second = provider.embed("салам привет")
    batch = provider.embed_many(["салам привет", "салам привет"])

    assert first == second
    assert batch == [first, second]
    assert len(first.values) == 32
    assert math.isclose(sum(value * value for value in first.values), 1.0, rel_tol=1e-6)


def test_pgvector_search_provider_returns_matches_only_in_complex_mode() -> None:
    """Семантический провайдер должен работать только в комплексном режиме."""
    entry = DictionaryEntry(source=DictionarySource.CORE, word="салам", translation="привет")
    provider = PgvectorSearchProvider(
        repository=SemanticRepositoryStub(
            [
                SemanticSearchCandidate(
                    entry=entry,
                    chunk_id=1,
                    chunk_type="translation",
                    chunk_text="привет",
                    distance=0.2,
                )
            ]
        ),
        embedding_provider=HashEmbeddingProvider(dimensions=32),
        top_k=3,
        max_distance=0.65,
    )

    assert provider.search("приветствие", SearchMode.LITE) == []

    matches = provider.search("приветствие", SearchMode.COMPLEX)

    assert [match.entry.title for match in matches] == ["салам - привет"]
    assert matches[0].score > 0


def test_pgvector_search_provider_filters_far_candidates() -> None:
    """Семантический провайдер не должен возвращать слишком далекие чанки."""
    provider = PgvectorSearchProvider(
        repository=SemanticRepositoryStub(
            [
                SemanticSearchCandidate(
                    entry=DictionaryEntry(
                        source=DictionarySource.CORE,
                        word="салам",
                        translation="привет",
                    ),
                    chunk_id=1,
                    chunk_type="translation",
                    chunk_text="привет",
                    distance=0.95,
                )
            ]
        ),
        embedding_provider=HashEmbeddingProvider(dimensions=32),
        top_k=3,
        max_distance=0.65,
    )

    assert provider.search("приветствие", SearchMode.COMPLEX) == []


def test_pgvector_search_provider_skips_noise_from_notes_and_comments() -> None:
    """Семантический поиск не должен возвращать note/comment-чанки как итоговую выдачу."""
    provider = PgvectorSearchProvider(
        repository=SemanticRepositoryStub(
            [
                SemanticSearchCandidate(
                    entry=DictionaryEntry(
                        source=DictionarySource.CORE,
                        word="уста",
                        translation="мастер",
                    ),
                    chunk_id=1,
                    chunk_type="note",
                    chunk_text="сов. устухи.",
                    distance=0.12,
                ),
                SemanticSearchCandidate(
                    entry=DictionaryEntry(
                        source=DictionarySource.CORE,
                        word="дихьхьана",
                        translation="мастер по насечке",
                    ),
                    chunk_id=2,
                    chunk_type="translation",
                    chunk_text="мастер по насечке",
                    distance=0.15,
                ),
            ]
        ),
        embedding_provider=HashEmbeddingProvider(dimensions=32),
        top_k=3,
        max_distance=0.65,
    )

    matches = provider.search("мастер по серебру", SearchMode.COMPLEX)

    assert [match.entry.title for match in matches] == ["дихьхьана - мастер по насечке"]


def test_pgvector_search_provider_filters_no_overlap_noise_when_overlap_exists() -> None:
    """Семантический поиск должен отрезать далекие no-overlap кандидаты при наличии overlap."""
    provider = PgvectorSearchProvider(
        repository=SemanticRepositoryStub(
            [
                SemanticSearchCandidate(
                    entry=DictionaryEntry(
                        source=DictionarySource.CORE,
                        word="хьайхъайвагъи",
                        translation="поприветствовать",
                    ),
                    chunk_id=1,
                    chunk_type="translation",
                    chunk_text="поприветствовать",
                    distance=0.17,
                ),
                SemanticSearchCandidate(
                    entry=DictionaryEntry(
                        source=DictionarySource.CORE,
                        word="вачIадихь",
                        translation="умильность, нежность",
                    ),
                    chunk_id=2,
                    chunk_type="title",
                    chunk_text="ВАЧIАДИХЬ - умильность, нежность",
                    distance=0.214,
                ),
            ]
        ),
        embedding_provider=HashEmbeddingProvider(dimensions=32),
        top_k=3,
        max_distance=0.65,
    )

    matches = provider.search("как поприветствовать человека", SearchMode.COMPLEX)

    assert [match.entry.title for match in matches] == ["хьайхъайвагъи - поприветствовать"]


def test_pgvector_search_provider_requires_overlap_for_example_chunks() -> None:
    """Семантические example-чанки без пересечения токенов должны отбрасываться как шум."""
    provider = PgvectorSearchProvider(
        repository=SemanticRepositoryStub(
            [
                SemanticSearchCandidate(
                    entry=DictionaryEntry(
                        source=DictionarySource.CORE,
                        word="майур",
                        translation="майор",
                    ),
                    chunk_id=1,
                    chunk_type="example",
                    chunk_text="майурра пагунте пагоны майора",
                    distance=0.149,
                ),
                SemanticSearchCandidate(
                    entry=DictionaryEntry(
                        source=DictionarySource.CORE,
                        word="дихьхьана",
                        translation="мастер по насечке",
                    ),
                    chunk_id=2,
                    chunk_type="translation",
                    chunk_text="мастер по насечке",
                    distance=0.146,
                ),
            ]
        ),
        embedding_provider=HashEmbeddingProvider(dimensions=32),
        top_k=3,
        max_distance=0.65,
    )

    matches = provider.search("мастер по серебру", SearchMode.COMPLEX)

    assert [match.entry.title for match in matches] == ["дихьхьана - мастер по насечке"]


def test_dictionary_rag_indexer_indexes_batches_with_progress_units() -> None:
    """Индексатор должен сохранять embeddings пакетно и отдельно учитывать ошибки."""
    repository = IndexRepositoryStub(
        [
            RagChunkRecord(
                chunk_id=1,
                entry_id=1,
                source=DictionarySource.CORE,
                chunk_type="translation",
                chunk_text="привет",
                normalized_chunk_text="привет",
                content_hash="1",
            ),
            RagChunkRecord(
                chunk_id=2,
                entry_id=1,
                source=DictionarySource.CORE,
                chunk_type="note",
                chunk_text="broken",
                normalized_chunk_text="broken",
                content_hash="2",
            ),
            RagChunkRecord(
                chunk_id=3,
                entry_id=2,
                source=DictionarySource.CORE,
                chunk_type="title",
                chunk_text="салам - привет",
                normalized_chunk_text="салам привет",
                content_hash="3",
            ),
        ]
    )
    indexer = DictionaryRagIndexer(
        repositories=(repository,),
        embedding_provider=FailingEmbeddingProvider(dimensions=32),
        batch_size=2,
    )

    indexed = indexer.sync_pending()

    assert indexed == 2
    assert len(repository.stored_batches) == 2
    assert [len(batch) for batch in repository.stored_batches] == [1, 1]
    assert repository.error_batches == [[(2, "boom")], []]
