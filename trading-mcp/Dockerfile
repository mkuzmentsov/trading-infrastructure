FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml /app/
COPY src /app/src

RUN pip install --upgrade pip && pip install .

EXPOSE 8765

CMD ["python", "-m", "trading_mcp"]
