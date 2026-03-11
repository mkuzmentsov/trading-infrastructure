FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    anthropic==0.50.0 \
    py-clob-client==0.19.0 \
    requests==2.32.3 \
    duckduckgo-search==6.3.7

CMD ["python", "-u", "/app/pm_claude.py"]
