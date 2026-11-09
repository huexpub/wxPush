# syntax=docker/dockerfile:1

# ---- 阶段一：构建 Vue 前端 ----
# 产物直接写进 wxpush/static（见 web/vite.config.js 的 outDir），
# 所以最终镜像里只有一个 Python 进程，不需要 nginx。
FROM node:22-alpine AS web

WORKDIR /app/web

COPY web/package.json web/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY web/ ./
RUN npm run build


# ---- 阶段二：运行时 ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WXPUSH_HOST=0.0.0.0 \
    WXPUSH_PORT=8000 \
    WXPUSH_DATA_DIR=/app/data

WORKDIR /app

COPY pyproject.toml README.md ./
COPY wxpush ./wxpush
COPY --from=web /app/wxpush/static ./wxpush/static

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && mkdir -p /app/data \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["python", "-m", "wxpush", "serve", "--host", "0.0.0.0", "--port", "8000"]
