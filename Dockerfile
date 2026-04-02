FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

COPY src ./src

CMD ["python", "src/main.py"]
