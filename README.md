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
  bot_app.py
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
ADMIN_CHAT_ID=-1000000000000
RAG_ENABLED=true
RAG_TOP_K=5
RAG_MAX_DISTANCE=0.65
RAG_EMBEDDING_PROVIDER=sentence-transformers
RAG_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RAG_EMBEDDING_DIMENSIONS=384
RAG_EMBEDDING_BATCH_SIZE=64
RAG_EMBEDDING_DEVICE=cpu
```

## Локальный запуск

```bash
python src/main.py
```

## Импорт словаря

Первичный перенос словаря из CSV в PostgreSQL запускается отдельно:

```bash
python src/import_dictionary.py
```

Или через `make`:

```bash
make import-dictionary
```

## Индексация RAG

Чанки словаря и таблицы под embeddings создаются автоматически, но полная векторная индексация запускается отдельно, чтобы не блокировать старт Telegram-бота:

```bash
make index-rag
```

По умолчанию проект использует локальный embedding provider на базе `sentence-transformers` и модели `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

Что важно:

- первый запуск `make index-rag` скачивает модель из Hugging Face и может идти несколько минут;
- после смены embedding-модели или размерности старые вектора автоматически помечаются как `pending`, и индексацию нужно прогнать заново;
- в `docker-compose.yml` для кэша Hugging Face уже подключен volume `hf_cache_slovar`, чтобы не скачивать модель при каждом пересоздании контейнера.

## Docker

```bash
docker compose up --build
```

В `docker-compose.yml` уже используется образ Postgres с `pgvector`.

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

Словарь хранится в нормализованной модели PostgreSQL, для RAG уже используются чанки, `pgvector` и локальная multilingual embedding-модель. Текущий `complex`-поиск опирается на semantic retrieval, а следующий практический шаг развития проекта — гибридный retrieval и затем генерация ответа через LLM поверх найденного контекста.
