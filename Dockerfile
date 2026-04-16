# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.bot.txt ./requirements.bot.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefer-binary -r requirements.bot.txt

COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

COPY src ./src

CMD ["python", "src/main.py"]
