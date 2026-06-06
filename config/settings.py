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
# Dance mode: one integrated scene still (girl + environment together), then
# animated by the Kling animator. DEFAULT_MODE is the fallback when a preset
# omits ``mode:``. The prompt template gets ``{theme}`` substituted in.
DEFAULT_MODE = env("DEFAULT_MODE", default="dance")
SCENE_IMAGE_MODEL = env("SCENE_IMAGE_MODEL", default="fal-ai/flux-pro/v1.1-ultra")
# Persistent character: when a dance preset gives `character.image`, the scene
# still is generated with that face locked in (same girl, new scenes) via a
# PuLID identity model instead of the text-only scene model. CHARACTER_ID_WEIGHT
# is PuLID's identity strength (higher = stricter to the reference face).
CHARACTER_SCENE_MODEL = env("CHARACTER_SCENE_MODEL", default="fal-ai/flux-pulid")
CHARACTER_ID_WEIGHT = env.float("CHARACTER_ID_WEIGHT", default=1.0)
# The scene prompt is {theme} (the setting) + {style} (the woman's look, swappable
# per-preset via `style:`) + an always-on safety clause. NOTE: the wardrobe stays
# this side of explicit on purpose — revealing outfits (bikini/lingerie) get the
# videos age-restricted and suppressed (→ ~0 views). DANCE_CHARACTER_STYLE is the
# default look when a preset gives no `style:`.
SCENE_PROMPT_TEMPLATE = env(
    "SCENE_PROMPT_TEMPLATE",
    default=(
        "a stunning attractive young woman dancing energetically in {theme}, "
        "{style}, tasteful and never explicit — no nudity, no lingerie, no "
        "swimwear, full body in frame, dynamic confident pose, cinematic lighting, "
        "photorealistic, highly detailed, vertical 9:16 composition, scroll-stopping"
    ),
)
# Used when a preset sets `framing: close` — an intimate chest-up portrait (the
# "cool girl" / e-girl posing format) instead of the full-body dance shot.
SCENE_PROMPT_CLOSE = env(
    "SCENE_PROMPT_CLOSE",
    default=(
        "a moody cinematic close-up portrait of a stunning attractive young woman, "
        "{style}, in {theme}, framed from the chest up, a stylish modeling pose "
        "looking toward the camera, soft moody lighting, photorealistic, highly "
        "detailed, vertical 9:16 composition, scroll-stopping, tasteful and never "
        "explicit — no nudity, no lingerie, no swimwear"
    ),
)
DANCE_CHARACTER_STYLE = env(
    "DANCE_CHARACTER_STYLE",
    default=(
        "wearing a stylish form-fitting outfit that flatters her figure — fitted "
        "activewear, a trendy crop top with high-waisted leggings, or a fitted mini "
        "dress, alluring and subtly sexy, with a fierce confident model expression"
    ),
)
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
# Dance mode drives Kling with its OWN, far more aggressive motion prompt (no
# lip-sync, so no "stay still / relaxed mouth" constraints) and a lower cfg to
# give the model freedom for big, explosive movement.
DANCE_KLING_CFG = env.float("DANCE_KLING_CFG", default=0.5)
# Beat-synced scene cuts: generate this many scenes (varied shot/angle) and
# hard-cut between them on the beat drops. 1 = single continuous scene (no extra
# cost). >1 multiplies the scene-gen + Kling spend by that factor.
DANCE_SCENE_CUTS = env.int("DANCE_SCENE_CUTS", default=1)
# Per-scene shot variation appended to the scene prompt (cycled) so cuts look
# like different angles, not a repeat.
DANCE_SHOT_VARIATIONS = env.list(
    "DANCE_SHOT_VARIATIONS",
    default=[
        "full-body wide shot",
        "medium shot from a different angle",
        "dynamic low-angle shot",
        "side-on full-body shot",
    ],
)
# Vibe mode: a clean cinematic "digital window" — a gorgeous scene (NO people,
# NO text) with a slow stabilized camera move, seamless loop, no captions/hook.
# Higher cfg keeps the motion gentle (closer to the still) than dance.
VIBE_KLING_CFG = env.float("VIBE_KLING_CFG", default=0.45)
VIBE_SCENE_PROMPT_TEMPLATE = env(
    "VIBE_SCENE_PROMPT_TEMPLATE",
    default=(
        "{theme}, breathtaking cinematic photography, dramatic twilight lighting, "
        "rich saturated colors, glowing neon reflections, ultra-detailed and crisp, "
        "atmospheric and dreamy, vertical 9:16 composition, no people, no text"
    ),
)
VIBE_MOTION_PROMPT = env(
    "VIBE_MOTION_PROMPT",
    default=(
        "a smooth cinematic flythrough — the camera glides steadily FORWARD through "
        "the scene as if the viewer is travelling through it, immersive dolly-forward "
        "motion with strong depth and parallax, drifting past and toward the elements, "
        "first-person travelling shot, clear sense of forward movement, smooth and "
        "cinematic (not shaky), no people, no text"
    ),
)
DANCE_MOTION_PROMPT = env(
    "DANCE_MOTION_PROMPT",
    default=(
        "explosive, extremely high-energy dancing — fast, powerful full-body movement, "
        "rapid hip sways, quick spins and turns, jumping, bouncing and grooving hard to a "
        "fast upbeat rhythm, dynamic athletic choreography, hair whipping, arms thrown wide, "
        "lots of motion, wild and electric energy, never static, the whole body keeps moving. "
        "She begins with a fierce, confident, pouty model stare, then near the end breaks "
        "into a big, bright, genuine smile (the charm pivot)"
    ),
)
# Mimic mode: motion transfer — a locked character performs the EXACT moves of a
# driving dance video. The appearance still (the character standing on a clean
# backdrop) is generated by the existing PuLID scene-gen; the driving video is
# downloaded + normalized to 9:16 (audio stripped). Output is MUTE (add the
# trending sound at post) + seamless-looped.
#
# Backend (MOTION_TRANSFER_PROVIDER):
#   "wan_animate" (default) — Alibaba Wan-2.2 Animate on fal. Purpose-built for
#       full-body character dance; far more coherent than MimicMotion (which
#       melts legs + busy backgrounds on energetic choreography).
#   "mimicmotion" — zsxkib/mimic-motion on Replicate (the original; kept as a
#       fallback). Soft + warps on fast full-body motion.
MOTION_TRANSFER_PROVIDER = env("MOTION_TRANSFER_PROVIDER", default="wan_animate")
# Wan-2.2 Animate (fal): image_url (character) + video_url (driving) -> video.
# "move"/animation mode = the character mimics the driving video's motion.
WAN_ANIMATE_MODEL = env("WAN_ANIMATE_MODEL", default="fal-ai/wan/v2.2-14b/animate/move")
WAN_ANIMATE_RESOLUTION = env("WAN_ANIMATE_RESOLUTION", default="720p")  # 480p|580p|720p
WAN_ANIMATE_QUALITY = env("WAN_ANIMATE_QUALITY", default="high")  # low|medium|high|maximum
WAN_ANIMATE_STEPS = env.int("WAN_ANIMATE_STEPS", default=20)
MIMICMOTION_MODEL = env(
    "MIMICMOTION_MODEL",
    default=(
        "zsxkib/mimic-motion:"
        "b3edd455f68ec4ccf045da8732be7db837cb8832d1a2459ef057ddcd3ff87dea"
    ),
)
# Output video HEIGHT in px (width auto-derived from the drive aspect). Model
# max is 1024; 576 (the model default) ends up ~324x576 for a 9:16 clip and
# looks soft once compose upscales it to 1080x1920, so we render at the max.
MIMICMOTION_RESOLUTION = env.int("MIMICMOTION_RESOLUTION", default=1024)
MIMICMOTION_FPS = env.int("MIMICMOTION_FPS", default=24)
# The appearance still: a clean, full-body, neutral standing pose. CRITICAL for
# quality — MimicMotion preserves the still's background + lighting into every
# frame, so a BRIGHT, well-lit, in-focus scene renders far crisper than a dark
# or busy one (dark + high-contrast neon maximizes the model's softness and
# compression noise). {theme} sets the setting; {style} the woman's look.
MIMIC_SCENE_PROMPT_TEMPLATE = env(
    "MIMIC_SCENE_PROMPT_TEMPLATE",
    default=(
        "a full-body photo of a stunning attractive young woman standing in a "
        "relaxed neutral pose facing the camera, {style}, in {theme}, bright and "
        "evenly lit, clean and uncluttered, in sharp crisp focus, well-exposed, "
        "head to toe fully in frame, photorealistic, highly detailed, vertical "
        "9:16 composition, tasteful and never explicit — no nudity, no lingerie, "
        "no swimwear"
    ),
)
# Driving-video normalization: scale-to-fill 9:16 at these dims, strip audio,
# cap length (cost control — MimicMotion price scales with frame count).
DRIVE_WIDTH = env.int("DRIVE_WIDTH", default=1080)
DRIVE_HEIGHT = env.int("DRIVE_HEIGHT", default=1920)
DRIVE_MAX_SECONDS = env.float("DRIVE_MAX_SECONDS", default=15.0)
KLING_MOTION_PROMPT = env(
    "KLING_MOTION_PROMPT",
    default=(
        "the character dances energetically — bobbing its head, swaying and bouncing "
        "to a heavy beat, arms moving rhythmically — while staying fully within the frame: "
        "the entire body, head and hands remain visible at all times, never cropped, no "
        "jumping out of frame. The mouth stays relaxed and mostly closed (a separate "
        "lip-sync pass adds the singing), the camera holds steady on the full body"
    ),
)
# Video lip-sync (maps a mouth onto an already-moving clip) for motion_first.
VIDEO_LIPSYNC_MODEL = env("VIDEO_LIPSYNC_MODEL", default="fal-ai/sync-lipsync/v2")

# Resync layer (motion_first only): Kling animates a small face in a full-body
# shot, so a whole-clip lip-sync barely moves the mouth. Instead, crop the head
# region, upscale it so the face is large, lip-sync THAT, then paste it back
# over the moving body (only the mouth differs, so the feathered blend is
# seamless). Window is a fraction of the 1080x1920 frame, generous enough to
# hold the head through the whole dance.
RESYNC_LAYER_ENABLED = env.bool("RESYNC_LAYER_ENABLED", default=True)
RESYNC_WIN_X_FRAC = env.float("RESYNC_WIN_X_FRAC", default=0.16)
RESYNC_WIN_Y_FRAC = env.float("RESYNC_WIN_Y_FRAC", default=0.02)
RESYNC_WIN_W_FRAC = env.float("RESYNC_WIN_W_FRAC", default=0.68)
RESYNC_WIN_H_FRAC = env.float("RESYNC_WIN_H_FRAC", default=0.46)
RESYNC_UPSCALE_H = env.int("RESYNC_UPSCALE_H", default=1280)
RESYNC_FEATHER_PX = env.int("RESYNC_FEATHER_PX", default=48)

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
BEAT_ZOOM = env.float("BEAT_ZOOM", default=1.035)
BEAT_DECAY_SECONDS = env.float("BEAT_DECAY_SECONDS", default=0.18)
KINETIC_BASE_ZOOM = env.float("KINETIC_BASE_ZOOM", default=1.0)
KINETIC_SHAKE_PX = env.float("KINETIC_SHAKE_PX", default=2.5)
# Trio layout knobs (as fractions of canvas height, except peek in px). Boss is
# the centre character; flanks are the two mirrored backups. flank_y_frac < 0
# bottom-anchors them (half-body dancers); >= 0 floats their centre at that
# height (small round companions like moons). flank_peek_px > 0 pushes flanks
# past the side edges; negative insets them fully on-screen.
TRIO_BOSS_HEIGHT_FRAC = env.float("TRIO_BOSS_HEIGHT_FRAC", default=0.64)
TRIO_FLANK_HEIGHT_FRAC = env.float("TRIO_FLANK_HEIGHT_FRAC", default=0.41)
TRIO_FLANK_Y_FRAC = env.float("TRIO_FLANK_Y_FRAC", default=-1.0)
TRIO_FLANK_PEEK_PX = env.int("TRIO_FLANK_PEEK_PX", default=40)

# Seamless looping (boosts replays on TikTok/Reels). Dance mode gives Kling the
# scene still as the END frame too (start == end → the motion returns home, a
# true seam-free loop). Closeup mode can't drive that, so compose dissolves the
# last LOOP_CROSSFADE_SECONDS back over the first (a soft xfade at the wrap).
LOOP_SEAMLESS_ENABLED = env.bool("LOOP_SEAMLESS_ENABLED", default=True)
LOOP_CROSSFADE_SECONDS = env.float("LOOP_CROSSFADE_SECONDS", default=0.4)
# How dance mode loops:
#   "crossfade" — Kling dances at full energy throughout; compose dissolves the
#                 wrap (energetic all the way, brief soft blend at the seam).
#   "endframe"  — Kling ends on the start frame (true seam-free loop, but the
#                 motion settles into the pose over the last ~second).
#   "off"       — no loop.
# Default crossfade: a stationary tail reads worse than a 0.4s dissolve.
DANCE_LOOP_MODE = env("DANCE_LOOP_MODE", default="crossfade")
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
