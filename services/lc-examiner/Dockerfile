# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
RUN useradd --uid 10001 --create-home app
COPY --from=build /install /usr/local
WORKDIR /srv
COPY app ./app
USER 10001
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
# Same image, two roles: API (default) or Kafka worker (`python -m app.worker`)
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
