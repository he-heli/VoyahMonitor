FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

# Playwright browser for interactive login inside container (optional)
RUN playwright install --with-deps chromium

RUN mkdir -p /app/data

VOLUME ["/app/data"]

CMD ["voyah-monitor", "bot"]
