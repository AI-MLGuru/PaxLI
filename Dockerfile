FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY apps ./apps
COPY core ./core
COPY infrastructure ./infrastructure
COPY integrations ./integrations

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "apps.api.averiq_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
