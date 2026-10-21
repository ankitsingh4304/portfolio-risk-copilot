FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
COPY eval ./eval

# Don't run as root inside the container.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# Database migrations run automatically when the app starts (see app/database.py).
# Render and similar hosts set $PORT. Default to 8000 locally. Keep ONE worker:
# more workers would each run the scheduler and send duplicate alerts.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
