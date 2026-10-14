FROM python:3.12-slim
WORKDIR /srv
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY app app
COPY migrations migrations
COPY web web
RUN useradd --system --no-create-home app && chown -R app /srv
USER app
EXPOSE 8000
# Compose runs migrations first (the `migrate` service); create_app's own migrate() is then a no-op check.
# The DB-backed rate limit makes several workers safe.
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
