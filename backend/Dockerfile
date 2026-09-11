# Imagem do backend para Railway (ou qualquer runtime de container).
#
# Duas etapas: a primeira instala dependencias com ferramentas de build (argon2-cffi
# e asyncpg compilam extensoes); a segunda copia so o resultado. A imagem final
# nao carrega compilador nem cache do pip.

FROM python:3.12-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
# `s3`: producao usa Cloudflare R2 (ADR-0007). O filesystem do container e efemero.
RUN pip install --no-cache-dir --prefix=/install ".[s3]"

FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    LOG_JSON=true

COPY --from=builder /install /usr/local
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Usuario sem privilegio: um RCE no processo nao ganha root no container.
RUN useradd --create-home --uid 1000 fsi && chown -R fsi:fsi /app
USER fsi

EXPOSE 8000

# Migrations antes de subir: a aplicacao nunca roda contra um schema desatualizado.
# `${PORT:-8000}` porque o Railway injeta a porta.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
