FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN useradd --create-home --uid 10001 app && chmod +x /usr/local/bin/entrypoint.sh
USER app

EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
# Hosts like Render assign $PORT; default to 8000 elsewhere.
CMD ["sh", "-c", "exec fastapi run app/main.py --host 0.0.0.0 --port ${PORT:-8000}"]
