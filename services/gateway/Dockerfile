# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
# Non-root, read-only-root-fs friendly (see deploy/k8s securityContext)
RUN useradd --uid 10001 --create-home app
COPY --from=build /install /usr/local
WORKDIR /srv
COPY app ./app
COPY config ./config
USER 10001
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 REGISTRY_PATH=/srv/config/models.yaml
EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
