"""Django settings for brainrot — the automated TikTok video pipeline."""

from __future__ import annotations

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-replace-me")
DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    # Unfold must come before django.contrib.admin so it can theme the
    # default admin site (standard unfold install — no custom admin site).
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_celery_beat",
    "django_celery_results",
    "core",
    "jobs",
    "stages",
    "providers",
    "compose",
    "delivery",
    "rest_framework",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

UNFOLD = {
    "SITE_TITLE": "Brainrot",
    "SITE_HEADER": "Brainrot",
    "SITE_SUBHEADER": "Video pipeline control",
    "SITE_URL": "/admin/",
    "THEME": "dark",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
}

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database — SQLite (WAL). Plenty at this job volume; no Postgres container.
# WAL + a busy_timeout keep the web process and the Celery worker from
# tripping over each other on the single SQLite writer. ``init_command`` for
# SQLite OPTIONS is supported on Django 5.1+.
# ---------------------------------------------------------------------------
DATABASE_PATH = env("DATABASE_PATH", default="db.sqlite3")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / DATABASE_PATH,
        "OPTIONS": {
            "timeout": 5,
            "init_command": (
                "PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL;PRAGMA busy_timeout=5000;"
            ),
        },
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Generated job artifacts (stems, frames, renders, final mp4s) live under
# media/jobs/<job_id>/. See core.storage for the path helpers.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Redis / Celery
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")
CELERY_BROKER_URL = REDIS_URL
# Store task results in SQLite via django-celery-results so the admin can
# list finished/in-progress/failed runs.
CELERY_RESULT_BACKEND = "django-db"
CELERY_TASK_TRACK_STARTED = True
CELERY_RESULT_EXTENDED = True
# When True, tasks run inline in the calling process (no worker needed) —
# this is how the test suite drives the full chain end-to-end.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TIMEZONE = "UTC"

# ---------------------------------------------------------------------------
# REST API — Bearer-key auth only (see api.auth). No session/basic auth so a
# logged-in admin session can't piggyback the API.
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["api.auth.ApiKeyAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

# ---------------------------------------------------------------------------
# Pipeline / provider config
# ---------------------------------------------------------------------------
# `fake` returns bundled fixture artifacts (no network, no spend); `real`
# calls the cloud vendors. Flip a single stage live by setting `real` and
# supplying that vendor's key.
PROVIDER_MODE = env("PROVIDER_MODE", default="fake")

# Replicate — Demucs (vocal separation) + WhisperX (caption alignment).
# Defaults pinned to verified model versions whose input schemas match the
# Real clients (audio+stem for Demucs; audio_file+align_output for WhisperX).
REPLICATE_API_TOKEN = env("REPLICATE_API_TOKEN", default="")
REPLICATE_DEMUCS_MODEL = env(
    "REPLICATE_DEMUCS_MODEL",
    default=("ryan5453/demucs:5a7041cc9b82e5a558fea6b3d7b12dea89625e89da33f0447bd727c2d0ab9e77"),
)
REPLICATE_WHISPERX_MODEL = env(
    "REPLICATE_WHISPERX_MODEL",
    default=(
        "victor-upmeet/whisperx:655845d6190ef70573c669245f245892cd039df4b880a1e3a65852c09252f5cc"
    ),
)

# fal — FLUX still + portrait, image->video background loop.
FAL_KEY = env("FAL_KEY", default="")
FAL_FLUX_MODEL = env("FAL_FLUX_MODEL", default="fal-ai/flux/dev")
FAL_IMAGE_TO_VIDEO_MODEL = env("FAL_IMAGE_TO_VIDEO_MODEL", default="fal-ai/wan-i2v")
# Invariant style layer appended to the per-video character identity (from the
# preset's character.description). Carries the project's look + the MANDATORY
# greenscreen (the compose stage chroma-keys it out) and full-body energetic
# framing. Override via env, but keep the green-screen clause or compositing
# breaks.
CHARACTER_STYLE_PROMPT = env(
    "CHARACTER_STYLE_PROMPT",
    default=(
        # Non-human Italian-brainrot creature — the scroll-stop is "what am I
        # looking at". Needs a face+mouth (lip-sync) and limbs (dancing).
        "absolutely not a human, a bizarre surreal Italian-brainrot creature, "
        "absurd object-animal hybrid with stubby limbs, full body dancing energetically "
        "mid-motion, two enormous googly eyes, a wide expressive toothy mouth, "
        "glossy hyper-real 3D render, cursed AI dreamcore, hyper-saturated clashing colors, "
        "maximalist chaotic, deeply weird scroll-stopping pattern-interrupt, "
        "sharp studio lighting, "
        # Mandatory — the compose stage chroma-keys this out.
        "solid chroma-key green screen background"
    ),
)

# Lip-sync vendor — one of: omnihuman | hedra | sync | magic_hour.
# omnihuman (Bytedance OmniHuman 1.5 on fal) animates the whole body to the
# audio — singing AND dancing — vs Hedra's talking-head. It's fed the full-mix
# clip (beat + vocals). Handles up to 30s @1080p / 60s @720p. Default because
# the brainrot creatures need full-body dancing motion.
LIPSYNC_PROVIDER = env("LIPSYNC_PROVIDER", default="omnihuman")
OMNIHUMAN_MODEL = env("OMNIHUMAN_MODEL", default="fal-ai/bytedance/omnihuman/v1.5")
OMNIHUMAN_RESOLUTION = env("OMNIHUMAN_RESOLUTION", default="1080p")
OMNIHUMAN_PROMPT = env(
    "OMNIHUMAN_PROMPT",
    default=(
        "performing with maximum intensity the entire time, dancing hard and nonstop "
        "with big full-body movements, bouncing to the beat, arms and hips moving, "
        "energetic showmanship, never standing still, exaggerated theatrical motion, "
        "singing passionately"
    ),
)
# Which audio the lip-sync model receives: "vocals" (isolated stem — best for
# talking-head mouth accuracy, e.g. Hedra) or "mix" (full clip with the beat —
# needed so a body-animating model like OmniHuman dances to the rhythm).
LIPSYNC_AUDIO_SOURCE = env("LIPSYNC_AUDIO_SOURCE", default="mix")
HEDRA_API_KEY = env("HEDRA_API_KEY", default="")
# Hedra audio-driven character model. Default is together/hedra-character-3
# (verified via GET /models: type=video, requires_audio_input, supports 9:16
# at 540p/720p/1080p, auto duration). Resolution defaults to the cheapest tier.
HEDRA_MODEL_ID = env("HEDRA_MODEL_ID", default="d1dd37a3-e39a-4854-a298-6510289f9cf2")
HEDRA_RESOLUTION = env("HEDRA_RESOLUTION", default="540p")
HEDRA_ASPECT_RATIO = env("HEDRA_ASPECT_RATIO", default="9:16")
SYNC_API_KEY = env("SYNC_API_KEY", default="")
MAGIC_HOUR_API_KEY = env("MAGIC_HOUR_API_KEY", default="")

# Telegram delivery.
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID", default="")

# Whether to render karaoke captions (drives the align_captions stage).
ENABLE_CAPTIONS = env.bool("ENABLE_CAPTIONS", default=True)
# Scroll-stop hook: a zoom-punch on the opening frames (starts zoomed in by
# INTRO_PUNCH_ZOOM, settles to 1.0x over INTRO_PUNCH_SECONDS). Visual-only —
# never touches lip-sync timing. Set zoom to 1.0 to disable.
INTRO_PUNCH_ZOOM = env.float("INTRO_PUNCH_ZOOM", default=1.35)
INTRO_PUNCH_SECONDS = env.float("INTRO_PUNCH_SECONDS", default=0.4)
# Recurring beat-pulse (the "drags at the end" fix). Parked at 1.0 (off): this
# ffmpeg's crop can't re-evaluate size per frame (no eval=frame), so a proper
# time-varying pulse needs a zoompan rework. The real motion lever is the
# lip-sync model (OmniHuman); revisit compose-level pulses later.
PULSE_ZOOM = env.float("PULSE_ZOOM", default=1.0)
PULSE_INTERVAL_SECONDS = env.float("PULSE_INTERVAL_SECONDS", default=1.5)
PULSE_DECAY_SECONDS = env.float("PULSE_DECAY_SECONDS", default=0.28)
# Force the WhisperX transcription language (ISO code, e.g. "es"). Empty =
# auto-detect. Auto-detect is unreliable on short non-English clips, so set
# this when the song isn't English. (A per-song preset field is the eventual
# home for this.)
WHISPERX_LANGUAGE = env("WHISPERX_LANGUAGE", default="")

# Bundled fixture assets the Fake providers return. Committed under fixtures/.
FIXTURES_DIR = BASE_DIR / "fixtures"

# ---------------------------------------------------------------------------
# Logging — operator-readable lifecycle events to stdout; structured state
# lives in the DB (Job/Artifact rows), not print() calls.
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
