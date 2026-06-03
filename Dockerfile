FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        # ffmpeg drives the entire compose stage (boomerang loop, chromakey
        # overlay, caption burn-in, guide-track mux, libx264 software encode).
        # The Pi 5 has no H.264 hardware encoder, so this software-encodes —
        # a 30-60s clip takes minutes, which is fine for an async pipeline.
        ffmpeg \
        # fontconfig + a font so libass can actually render burned-in
        # captions; without a font the subtitles filter draws nothing.
        fontconfig \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# uv for fast dependency resolution
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first for layer caching. README.md is copied alongside
# pyproject.toml because hatchling references it in [project.readme].
COPY pyproject.toml README.md ./
COPY uv.lock* ./
RUN uv pip install --system --no-cache ".[dev]"

# Copy source
COPY . .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
