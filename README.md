# Kubachi Slovar Bot

Telegram-бот для поиска по кубачинско-русскому словарю.

Сейчас проект работает на `aiogram v3`, использует PostgreSQL как основное хранилище словаря и поддерживает два слоя поиска:
- обычный лексический поиск по словарным статьям;
- семантический retrieval через `pgvector`.

CSV-файлы нужны только для отдельной одноразовой команды импорта словаря.

## Структура

```text
src/
  main.py
  import_dictionary.py
  index_rag.py
  config.py
  models.py
  normalization.py
  texts.py
  repositories/
  services/
tests/
```

## Требования

- Python `3.10 - 3.12`
- Docker и Docker Compose, если запускать контейнерно
- PostgreSQL 16 с расширением `pgvector`, если запускать без Docker

## Установка

Если используешь `uv`:

```bash
uv sync --all-groups
```

Если используешь `venv` и `pip`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Переменные окружения

Создай `.env` со значениями. Его загружает `pydantic-settings`.

```env
BOT_TOKEN=...
DB_HOST=db
DB_PORT=5432
DB_USER=bot
DB_PASSWORD=secret007
DB_NAME=kubachi_db
LOGS_CHAT_ID=-1000000000000
ADMINS_CHAT_IDS=123456789,987654321
RAG_ENABLED=true
RAG_TOP_K=5
RAG_MAX_DISTANCE=0.65
RAG_EMBEDDING_PROVIDER=http
RAG_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RAG_EMBEDDING_DIMENSIONS=384
RAG_EMBEDDING_BATCH_SIZE=64
RAG_EMBEDDING_DEVICE=cpu
RAG_EMBEDDING_SERVICE_URL=http://embeddings:8080
RAG_EMBEDDING_SERVICE_TIMEOUT_SECONDS=15
EMBEDDING_SERVICE_PROVIDER=sentence-transformers
EMBEDDING_SERVICE_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
EMBEDDING_SERVICE_DIMENSIONS=384
EMBEDDING_SERVICE_BATCH_SIZE=64
EMBEDDING_SERVICE_DEVICE=cpu
EMBEDDING_SERVICE_HOST=0.0.0.0
EMBEDDING_SERVICE_PORT=8080
```

Где:
- `LOGS_CHAT_ID` — чат или группа, куда бот отправляет служебные уведомления и предложения из `/suggest`;
- `ADMINS_CHAT_IDS` — список `chat_id` админов через запятую, которым доступна `/admin`.

## Локальный запуск

Перед первым запуском примени миграции:

```bash
make db-upgrade
```

Потом запускай бота:

```bash
python src/main.py
```

## Импорт словаря

Первичный перенос словаря из CSV в PostgreSQL запускается отдельно, после `make db-upgrade`:

```bash
python src/import_dictionary.py
```

Или через `make`:

```bash
make import-dictionary
```

## Миграции БД

Схема приложения теперь описана через Alembic, и приложение больше не создает таблицы само во время старта. Каноничный способ поднимать и обновлять схему теперь такой:

```bash
make db-upgrade
```

Полезные команды:

```bash
make db-current
make db-downgrade
make db-revision ARGS="-m \"новая миграция\""
```

Первая миграция уже содержит текущую структуру таблиц приложения, словаря и RAG, так что ее можно применить и к пустой базе, и к уже существующей dev-базе.
Команды `db-upgrade`, `db-current`, `db-downgrade` и `db-revision` запускаются через `docker compose`, чтобы работать с той же Docker-окружением и `.env`-настройкой, где `DB_HOST=db`.

## Индексация RAG

Чанки словаря синхронизируются ботом автоматически, но полная векторная индексация запускается отдельно, после `make db-upgrade`, чтобы не блокировать старт Telegram-бота:

```bash
make index-rag
```

Рекомендуемый режим для Docker-развертывания: бот обращается к отдельному embedding-сервису по HTTP.

По умолчанию `.env.example` настроен так:

- `RAG_EMBEDDING_PROVIDER=http`
- `RAG_EMBEDDING_SERVICE_URL=http://embeddings:8080`
- отдельный сервис `embeddings` сам держит локальную модель `sentence-transformers`

Если embedding-сервис работает на другом сервере, достаточно поменять только:

```env
RAG_EMBEDDING_SERVICE_URL=http://your-host:8080
```

Что важно:

- первый запуск embedding-сервиса скачивает модель из Hugging Face и может идти несколько минут;
- после смены embedding-модели или размерности старые вектора автоматически помечаются как `pending`, и индексацию нужно прогнать заново;
- в `docker-compose.yml` для кэша Hugging Face уже подключен volume `hf_cache_slovar`, чтобы не скачивать модель при каждом пересоздании контейнера;
- боту локальная embedding-модель больше не нужна, если он работает через `RAG_EMBEDDING_PROVIDER=http`.

### Отдельный embedding-сервис

Локально его можно запустить так:

```bash
uv run python -m embedding_service.main
```

Или отдельным Docker-контейнером:

```bash
docker compose --profile embedder up --build embeddings
```

Тогда бот и ручная переиндексация могут обращаться к нему по адресу из `RAG_EMBEDDING_SERVICE_URL`.

## Retrieval Benchmark

Для сравнения `lexical`, `semantic` и `hybrid` режима есть отдельный benchmark-раннер на фиксированном наборе запросов:

```bash
make benchmark-retrieval
```

Команда ходит в локальный Postgres-контейнер через `localhost:5434`, поэтому перед запуском держи поднятым хотя бы `docker compose up -d db`.

Можно передать свои параметры через `ARGS`, например:

```bash
make benchmark-retrieval ARGS="--top-k 10 --repeat 10 --output benchmarks/results/latest.json"
```

Набор кейсов лежит в [benchmarks/retrieval_cases.json](benchmarks/retrieval_cases.json). Скрипт выводит summary по quality-метрикам и latency, а при `--output` сохраняет подробный JSON-отчет.

## Админ-панель

В боте предусмотрен отдельный раздел для администратора через `/admin`.

Что должно быть доступно в панели:

- рассылка всем пользователям, активным за N дней и тем, кто хотя бы раз писал боту;
- превью рассылки перед отправкой и отчет по результату;
- список пользовательских статей с автором, датой, полным текстом, фильтрами и удалением;
- список комментариев с привязкой к статье, автором, датой и удалением;
- статистика по пользователям, запросам, статьям, комментариям и предложениям;
- отдельный список предложений, пришедших через `/suggest`.

Панель остается Telegram-based, без отдельного веб-интерфейса.

## Интеграционные тесты

Интеграционные тесты гоняются по живому `docker compose`-стеку и по умолчанию пропускаются в обычном `make project-check`.

Запуск:

```bash
make test-integration
```

Команда сама поднимает `db`, применяет Alembic-миграции и гоняет `pytest --integration` против живого Postgres/pgvector на `localhost:5434`.

## Docker

```bash
docker compose up --build
```

В `docker-compose.yml` уже используется образ Postgres с `pgvector`.

Если нужен локальный embedding-сервис в отдельном контейнере:

```bash
docker compose --profile embedder up --build
```

## Проверки

```bash
make lint
make doclint
make format-check
make type-check
make test
```

Или все сразу:

```bash
make project-check
```

## Статус проекта

Словарь хранится в нормализованной модели PostgreSQL, для RAG уже используются чанки, `pgvector` и отдельный embedding-сервис. Текущий `complex`-поиск опирается на semantic retrieval, а следующий практический шаг развития проекта — гибридный retrieval и затем генерация ответа через LLM поверх найденного контекста.
