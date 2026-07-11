FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aggregator ./aggregator
COPY recorder ./recorder

EXPOSE 8080
CMD ["python", "-m", "aggregator.main"]
