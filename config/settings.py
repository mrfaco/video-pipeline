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
        "mid-motion, two enormous googly eyes, a relaxed mostly-closed mouth with clear "
        "defined lips (NOT a fixed wide-open grin) so it can lip-sync, glossy hyper-real "
        "3D render, cursed AI dreamcore, hyper-saturated clashing colors, "
        # The creature MUST avoid green — green is chroma-keyed out and would
        # leave transparent holes in the character.
        "the creature itself uses vivid NON-green colors only (no green parts), "
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
        # Content-neutral (works for spoken or sung audio) + AGGRESSIVE motion
        # (directional, high-momentum phrasing per the high-motion playbook).
        "lip-syncing the audio accurately, mouth matching the words, performing with "
        "maximum intensity, aggressively bobbing the head up and down with maximum "
        "momentum on the hard rhythm, bouncing hard to the beat, explosive full-body "
        "movements, arms and hips snapping sharply, jumping, kinetic high-energy "
        "showmanship, never standing still"
    ),
)
# Animation approach:
#   "lipsync"      — OmniHuman on the static portrait (accurate mouth, modest
#                    body motion — the "animated photo" look).
#   "motion_first" — Kling animates the portrait with aggressive full-body
#                    motion, THEN a video lip-sync maps the mouth onto the
#                    moving clip. Chaotic viral energy; mouth is close, not
#                    phoneme-perfect. Two generation calls per character, and
#                    bounded to KLING_DURATION (Kling's max clip length).
MOTION_MODE = env("MOTION_MODE", default="lipsync")
KLING_MODEL = env("KLING_MODEL", default="fal-ai/kling-video/v2.5-turbo/pro/image-to-video")
KLING_DURATION = env("KLING_DURATION", default="10")  # "5" or "10" seconds
KLING_CFG = env.float("KLING_CFG", default=0.8)
KLING_MOTION_PROMPT = env(
    "KLING_MOTION_PROMPT",
    default=(
        "the character aggressively bobs its head up and down with maximum momentum, "
        "bouncing hard side to side, explosive energetic dancing, jumping, arms swinging, "
        "kinetic high-energy motion, mouth snapping open and shut rhythmically to a heavy beat"
    ),
)
# Video lip-sync (maps a mouth onto an already-moving clip) for motion_first.
VIDEO_LIPSYNC_MODEL = env("VIDEO_LIPSYNC_MODEL", default="fal-ai/sync-lipsync/v2")

# Matting: after lip-sync, cut the character out by SUBJECT segmentation
# (BiRefNet on fal) instead of chroma-keying green — so green clothes, green
# creatures, and thin limbs stay solid. The model caps at MATTING_MAX_FRAMES,
# so longer clips are downsampled in fps to fit.
MATTING_ENABLED = env.bool("MATTING_ENABLED", default=True)
MATTING_MODEL = env("MATTING_MODEL", default="fal-ai/birefnet/v2/video")
MATTING_MODEL_VARIANT = env("MATTING_MODEL_VARIANT", default="Matting")
# ProRes 4444 .mov, not VP9 .webm: webm alpha is a secondary stream that ffmpeg
# decodes inconsistently across frames (intermittent opaque-black boxes in the
# composite). ProRes is all-intra with a reliable alpha plane.
MATTING_OUTPUT_TYPE = env("MATTING_OUTPUT_TYPE", default="PRORES4444 (.mov)")
MATTING_MAX_FRAMES = env.int("MATTING_MAX_FRAMES", default=512)

# Which audio the lip-sync model receives: "vocals" (isolated stem — clean
# voice, so lip-sync stays accurate even when the song is music-heavy and the
# vocals are buried in the mix) or "mix" (full clip — more beat-driven body
# motion, but the mouth can track the music instead of the voice). The viewer
# always hears the full mix in the mux; this only affects what the model syncs
# to. Default "vocals" because reliable lip-sync beats marginally better dance.
LIPSYNC_AUDIO_SOURCE = env("LIPSYNC_AUDIO_SOURCE", default="vocals")
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
# Kinetic camera: a beat-synced zoom punch + always-on handheld shake, done
# with a per-frame zoompan (which DOES re-evaluate every frame, unlike crop).
# librosa detects the beat grid from the song; compose pulses BEAT_ZOOM on each
# beat, decaying over BEAT_DECAY_SECONDS. KINETIC_SHAKE_PX adds a continuous
# handheld jitter (compose auto-derives the crop headroom it needs over
# KINETIC_BASE_ZOOM). Visual-only — never touches lip-sync timing. Set
# KINETIC_ENABLED off, or BEAT_ZOOM=1.0 + shake=0, to disable.
KINETIC_ENABLED = env.bool("KINETIC_ENABLED", default=True)
BEAT_ZOOM = env.float("BEAT_ZOOM", default=1.06)
BEAT_DECAY_SECONDS = env.float("BEAT_DECAY_SECONDS", default=0.18)
KINETIC_BASE_ZOOM = env.float("KINETIC_BASE_ZOOM", default=1.0)
KINETIC_SHAKE_PX = env.float("KINETIC_SHAKE_PX", default=6.0)
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
