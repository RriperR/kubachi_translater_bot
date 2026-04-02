# Kubachi Slovar Bot

Telegram-бот для поиска по кубачинско-русскому словарю.

Сейчас проект работает на `aiogram v3`, использует PostgreSQL как основное хранилище словаря, а CSV нужны только для отдельной команды одноразового импорта.
Структура кода уже разрезана на слои, чтобы дальше без переделки Telegram-слоя можно было добавлять:

- индексатор словаря
- эмбеддинги
- vector storage
- retrieval / reranking
- RAG и LLM-интеграции

## Структура

```text
src/
  main.py
  import_dictionary.py
  bot_app.py
  config.py
  models.py
  normalization.py
  texts.py
  Slovar_14_08.csv
  users_translates.csv
  repositories/
  services/
```

## Требования

- Python `3.10 - 3.12`
- Docker и Docker Compose, если запускать контейнерно
- PostgreSQL 16, если запускать без Docker

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

Создай `.env` со значениями. Его загрузит `pydantic-settings`:

```env
BOT_TOKEN=...
DB_HOST=db
DB_PORT=5432
DB_USER=bot
DB_PASSWORD=secret007
DB_NAME=kubachi_db
ADMIN_CHAT_ID=-1000000000000
```

## Локальный запуск

```bash
python src/main.py
```

## Импорт словаря

Первичный перенос словаря из CSV в PostgreSQL запускается отдельной командой:

```bash
python src/import_dictionary.py
```

Или через `make`:

```bash
make import-dictionary
```

## Docker

```bash
docker compose up --build
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

Сейчас это асинхронный Telegram-бот с PostgreSQL как основным хранилищем.
Следующий логичный этап развития: вынести словарные данные в нормализованную модель, добавить индекс поиска и затем подключать RAG поверх отдельного retrieval-слоя.
