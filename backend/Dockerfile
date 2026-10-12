# UNTESTED: written without a running Docker daemon. Build and run it once before relying on it.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY migrations migrations
COPY web web
RUN useradd --system --no-create-home app && chown -R app /srv
USER app
EXPOSE 8000
# Migrations run at startup (create_app); the DB-backed rate limit makes several workers safe.
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
