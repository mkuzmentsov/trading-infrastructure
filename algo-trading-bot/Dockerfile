# Minimal image for running the paper/live engine and the research CLI locally.
FROM python:3.12-slim

WORKDIR /app

# Install the package first (cached unless deps change). storage = parquet/duckdb,
# venues = ccxt (data fetch + live polling). Add the `ml` extra if you want `metalabel`.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[storage,venues]"

COPY configs ./configs

# Data and runtime state are mounted as volumes (see docker-compose.yml).
VOLUME ["/app/data", "/app/state"]

ENTRYPOINT ["atb"]
# Default: paper-trade by replaying stored bars at 2 bars/sec. Override in compose.
CMD ["paper", "--config", "configs/paper.toml", "--source", "replay", "--speed", "2", "--state-dir", "/app/state"]
