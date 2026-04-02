"""Benchmark lexical, semantic и hybrid retrieval на фиксированном наборе запросов."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from time import perf_counter_ns

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import AppConfig, load_config
from models import DictionarySource, SearchMode
from normalization import normalize_query
from repositories.postgres import PostgresDictionaryRepository
from services.rag import PgvectorSearchProvider, build_embedding_provider
from services.search import DictionarySearchService, LexicalSearchProvider

DEFAULT_CASES_PATH = Path(__file__).with_name("retrieval_cases.json")
DEFAULT_MODES = ("lexical", "semantic", "hybrid")


@dataclass(frozen=True)
class BenchmarkCase:
    """Один запрос с ожидаемыми релевантными статьями."""

    query: str
    expected_words: tuple[str, ...]


@dataclass(frozen=True)
class CaseResult:
    """Результат замера одного запроса в одном режиме."""

    query: str
    expected_words: tuple[str, ...]
    hit_at_1: bool
    hit_at_k: bool
    best_rank: int | None
    median_latency_ms: float
    mean_latency_ms: float
    samples_ms: tuple[float, ...]
    top_titles: tuple[str, ...]


@dataclass(frozen=True)
class ModeResult:
    """Агрегированные метрики для одного режима retrieval."""

    mode: str
    cases: tuple[CaseResult, ...]
    hit_at_1: float
    hit_at_k: float
    mrr_at_k: float
    avg_latency_ms: float
    p95_latency_ms: float


def main() -> None:
    """Запустить retrieval benchmark из командной строки."""
    args = parse_args()
    cases = load_cases(args.cases)
    config = load_config()
    services = build_services(config, args.top_k)

    selected_modes = tuple(resolve_modes(args.modes))
    results: list[ModeResult] = []
    for mode_name in selected_modes:
        service = services.get(mode_name)
        if service is None:
            print(f"[skip] {mode_name}: semantic retrieval disabled in config")
            continue
        results.append(run_mode(mode_name, service, cases, args.top_k, args.warmup, args.repeat))

    print_summary(results, args.top_k)
    if args.output is not None:
        write_json(args.output, cases, results, args.top_k)


def parse_args() -> argparse.Namespace:
    """Разобрать CLI-аргументы benchmark-скрипта.

    Returns:
        Namespace с распарсенными CLI-аргументами.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help="Путь к JSON-файлу с benchmark-кейсами.",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=(*DEFAULT_MODES, "all"),
        default=["all"],
        help="Набор режимов: lexical, semantic, hybrid или all.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Размер top-k для quality-метрик.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Число прогревочных запусков на запрос.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=5,
        help="Число измеряемых прогонов на запрос.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Путь для JSON-отчета с подробными результатами.",
    )
    return parser.parse_args()


def resolve_modes(raw_modes: list[str]) -> list[str]:
    """Нормализовать выбор режимов.

    Args:
        raw_modes: Сырые значения режима из CLI.

    Returns:
        Список режимов, который будет реально запущен.
    """
    return list(DEFAULT_MODES) if raw_modes == ["all"] else raw_modes


def load_cases(path: Path) -> tuple[BenchmarkCase, ...]:
    """Загрузить benchmark-кейсы из JSON.

    Args:
        path: Путь к JSON-файлу с кейсами.

    Returns:
        Кортеж benchmark-кейсов.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[BenchmarkCase] = []
    for item in data:
        cases.append(
            BenchmarkCase(
                query=str(item["query"]),
                expected_words=tuple(str(word) for word in item["expected_words"]),
            )
        )
    return tuple(cases)


def build_services(
    config: AppConfig,
    top_k: int,
) -> dict[str, DictionarySearchService]:
    """Собрать retrieval-сервисы для benchmark-режимов.

    Args:
        config: Конфигурация приложения.
        top_k: Размер top-k для semantic retrieval.

    Returns:
        Словарь retrieval-сервисов по именам режимов.
    """
    main_repository = PostgresDictionaryRepository(config.database, DictionarySource.CORE)
    user_repository = PostgresDictionaryRepository(config.database, DictionarySource.USER)

    lexical_service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(main_repository),
            LexicalSearchProvider(user_repository),
        )
    )

    services: dict[str, DictionarySearchService] = {
        "lexical": lexical_service,
    }

    if not config.rag_enabled:
        return services

    embedding_provider = build_embedding_provider(config)
    semantic_providers = (
        PgvectorSearchProvider(
            repository=main_repository,
            embedding_provider=embedding_provider,
            top_k=top_k,
            max_distance=config.rag_max_distance,
        ),
        PgvectorSearchProvider(
            repository=user_repository,
            embedding_provider=embedding_provider,
            top_k=top_k,
            max_distance=config.rag_max_distance,
        ),
    )
    semantic_service = DictionarySearchService(providers=semantic_providers)
    hybrid_service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(main_repository),
            LexicalSearchProvider(user_repository),
            *semantic_providers,
        )
    )
    services["semantic"] = semantic_service
    services["hybrid"] = hybrid_service
    return services


def run_mode(
    mode_name: str,
    service: DictionarySearchService,
    cases: tuple[BenchmarkCase, ...],
    top_k: int,
    warmup: int,
    repeat: int,
) -> ModeResult:
    """Прогнать один режим retrieval по всему набору кейсов.

    Args:
        mode_name: Имя режима benchmark.
        service: Готовый retrieval-сервис.
        cases: Набор benchmark-кейсов.
        top_k: Размер top-k для quality-метрик.
        warmup: Число прогревочных прогонов.
        repeat: Число измеряемых прогонов.

    Returns:
        Аггрегированные метрики режима и результаты по кейсам.
    """
    case_results = tuple(
        run_case(service, case, top_k=top_k, warmup=warmup, repeat=repeat) for case in cases
    )

    hit_at_1 = mean(1.0 if case.hit_at_1 else 0.0 for case in case_results)
    hit_at_k = mean(1.0 if case.hit_at_k else 0.0 for case in case_results)
    mrr_at_k = mean(
        (1.0 / case.best_rank) if case.best_rank and case.best_rank <= top_k else 0.0
        for case in case_results
    )
    all_samples = [sample for case in case_results for sample in case.samples_ms]
    avg_latency_ms = mean(all_samples) if all_samples else 0.0
    p95_latency_ms = percentile(all_samples, 0.95)

    return ModeResult(
        mode=mode_name,
        cases=case_results,
        hit_at_1=hit_at_1,
        hit_at_k=hit_at_k,
        mrr_at_k=mrr_at_k,
        avg_latency_ms=avg_latency_ms,
        p95_latency_ms=p95_latency_ms,
    )


def run_case(
    service: DictionarySearchService,
    case: BenchmarkCase,
    *,
    top_k: int,
    warmup: int,
    repeat: int,
) -> CaseResult:
    """Замерить один запрос и вычислить quality/latency метрики.

    Args:
        service: Retrieval-сервис для benchmark.
        case: Кейс с запросом и ожидаемыми статьями.
        top_k: Размер top-k для quality-метрик.
        warmup: Число прогревочных прогонов.
        repeat: Число измеряемых прогонов.

    Returns:
        Метрики для одного кейса в одном режиме.
    """
    samples: list[float] = []
    results: list[str] = []
    for iteration in range(warmup + repeat):
        started_at = perf_counter_ns()
        entries = service.search(case.query, SearchMode.COMPLEX)
        elapsed_ms = (perf_counter_ns() - started_at) / 1_000_000
        if iteration >= warmup:
            samples.append(elapsed_ms)
        if not results:
            results = [entry.title for entry in entries]

    best_rank = find_best_rank(results, case.expected_words)
    hit_at_1 = best_rank == 1
    hit_at_k = best_rank is not None and best_rank <= top_k
    return CaseResult(
        query=case.query,
        expected_words=case.expected_words,
        hit_at_1=hit_at_1,
        hit_at_k=hit_at_k,
        best_rank=best_rank,
        median_latency_ms=median(samples) if samples else 0.0,
        mean_latency_ms=mean(samples) if samples else 0.0,
        samples_ms=tuple(samples),
        top_titles=tuple(results[:top_k]),
    )


def find_best_rank(results: list[str], expected_words: tuple[str, ...]) -> int | None:
    """Найти лучшую позицию ожидаемой статьи в выдаче.

    Args:
        results: Список title из результатов поиска.
        expected_words: Набор ожидаемых слов статьи.

    Returns:
        Лучший 1-based индекс совпадения или `None`, если совпадения нет.
    """
    expected = {normalize_query(word) for word in expected_words}
    for index, title in enumerate(results, start=1):
        if normalize_query(title.split(" - ", 1)[0]) in expected:
            return index
    return None


def percentile(samples: list[float], quantile: float) -> float:
    """Вычислить квантиль без внешних зависимостей.

    Args:
        samples: Набор значений в миллисекундах.
        quantile: Квантиль в диапазоне от 0 до 1.

    Returns:
        Значение квантиля или `0.0`, если выборка пустая.
    """
    if not samples:
        return 0.0
    ordered = sorted(samples)
    position = int(round((len(ordered) - 1) * quantile))
    position = max(0, min(position, len(ordered) - 1))
    return ordered[position]


def print_summary(results: list[ModeResult], top_k: int) -> None:
    """Вывести краткий текстовый отчет в stdout.

    Args:
        results: Результаты benchmark по режимам.
        top_k: Размер top-k для quality-метрик.
    """
    if not results:
        print("Нет доступных режимов для benchmark.")
        return

    print(f"top-k: {top_k}")
    for mode_result in results:
        print()
        print(
            f"{mode_result.mode}: hit@1={mode_result.hit_at_1:.2f}, "
            f"hit@{top_k}={mode_result.hit_at_k:.2f}, "
            f"mrr@{top_k}={mode_result.mrr_at_k:.2f}, "
            f"avg={mode_result.avg_latency_ms:.1f}ms, "
            f"p95={mode_result.p95_latency_ms:.1f}ms"
        )
        for case in mode_result.cases:
            expected = ", ".join(case.expected_words)
            top = ", ".join(case.top_titles[:top_k]) or "-"
            rank = case.best_rank if case.best_rank is not None else "-"
            print(
                f"  - {case.query}: rank={rank}, "
                f"median={case.median_latency_ms:.1f}ms, "
                f"expected={expected}, top={top}"
            )


def write_json(
    path: Path,
    cases: tuple[BenchmarkCase, ...],
    results: list[ModeResult],
    top_k: int,
) -> None:
    """Сохранить подробный JSON-отчет.

    Args:
        path: Путь к выходному JSON-файлу.
        cases: Исходный набор benchmark-кейсов.
        results: Результаты benchmark по режимам.
        top_k: Размер top-k для quality-метрик.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "top_k": top_k,
        "cases": [
            {"query": case.query, "expected_words": list(case.expected_words)} for case in cases
        ],
        "results": [
            {
                "mode": result.mode,
                "hit_at_1": result.hit_at_1,
                "hit_at_k": result.hit_at_k,
                "mrr_at_k": result.mrr_at_k,
                "avg_latency_ms": result.avg_latency_ms,
                "p95_latency_ms": result.p95_latency_ms,
                "cases": [
                    {
                        "query": case.query,
                        "expected_words": list(case.expected_words),
                        "hit_at_1": case.hit_at_1,
                        "hit_at_k": case.hit_at_k,
                        "best_rank": case.best_rank,
                        "median_latency_ms": case.median_latency_ms,
                        "mean_latency_ms": case.mean_latency_ms,
                        "samples_ms": list(case.samples_ms),
                        "top_titles": list(case.top_titles),
                    }
                    for case in result.cases
                ],
            }
            for result in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
