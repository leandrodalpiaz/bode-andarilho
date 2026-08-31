# Build único: Node compila a PWA; Python serve o artefato e as APIs na mesma origem.
FROM node:22-bookworm AS frontend-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/ ./
RUN npm run typecheck && npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PWA_FRONTEND_DIST=/app/web/dist
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . ./
COPY --from=frontend-build /build/web/dist ./web/dist
EXPOSE 10000
CMD ["python", "main.py"]
