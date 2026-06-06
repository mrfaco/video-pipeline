"""Provider interfaces + the Real/Fake selection factory.

Every cloud-backed stage talks to one of these small clients rather than an
SDK directly. Two backends implement each interface:

* ``Real*`` — HTTP to Replicate / fal / a lip-sync vendor (in ``replicate.py``,
  ``fal.py``, ``lipsync.py``). Heavy SDK imports are deferred to the callsite
  so a fake-only run never needs them installed.
* ``Fake*`` — returns a bundled fixture artifact (copied into the job dir),
  no network, no spend. This is what lets the whole chain run end-to-end in
  tests and in the default dev loop.

``settings.PROVIDER_MODE`` (``fake`` | ``real``) selects which backend the
``get_*`` factories below return. Loud failures everywhere: a Real client with
a missing key raises at construction, never silently degrades (AGENTS.md §1).

The concrete classes the factories import are built in the sibling modules:
    replicate.py : RealDemucsSeparator, RealWhisperXAligner
    fal.py       : RealFalBackgroundGenerator, RealFalPortraitGenerator
    lipsync.py   : RealHedraLipSyncer, RealSyncLipSyncer, RealMagicHourLipSyncer
    fakes.py     : FakeVocalSeparator, FakeCaptionAligner, FakeBackgroundGenerator,
                   FakePortraitGenerator, FakeLipSyncer
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from django.conf import settings


class ProviderConfigError(RuntimeError):
    """Raised when a Real provider is selected but its config/key is missing."""


@runtime_checkable
class VocalSeparator(Protocol):
    def separate(self, song_path: Path, out_path: Path) -> Path:
        """Extract a clean vocal stem from ``song_path``, writing ``out_path``."""
        ...


@runtime_checkable
class CaptionAligner(Protocol):
    def align(self, audio_path: Path, lyrics: str | None, out_path: Path) -> Path:
        """Produce word-level timestamps as JSON at ``out_path`` and return it."""
        ...


@runtime_checkable
class BackgroundGenerator(Protocol):
    def generate_still(self, theme: str, out_path: Path) -> Path:
        """FLUX still frame from the theme prompt."""
        ...

    def animate(self, still_path: Path, out_path: Path) -> Path:
        """Image->video motion loop (~5s) from the still."""
        ...


@runtime_checkable
class PortraitGenerator(Protocol):
    def generate(self, character_ref: str, out_path: Path) -> Path:
        """Ultra-realistic greenscreen portrait for the locked character."""
        ...


@runtime_checkable
class SceneGenerator(Protocol):
    def generate(
        self, prompt: str, out_path: Path, reference_image: Path | None = None
    ) -> Path:
        """One integrated scene still (character + environment) for dance mode.

        ``reference_image`` locks a persistent character's face into the scene
        (identity-preserving generation); None = a fresh same-vibe woman.
        """
        ...


@runtime_checkable
class LipSyncer(Protocol):
    def sync(self, portrait_path: Path, audio_path: Path, out_path: Path) -> Path:
        """Talking-head clip: portrait lip-synced to ``audio_path``."""
        ...


@runtime_checkable
class Matter(Protocol):
    def matte(self, video_in: Path, out_path: Path) -> Path:
        """Cut the subject out of ``video_in``, writing a clip with alpha."""
        ...


@runtime_checkable
class Animator(Protocol):
    def animate(
        self,
        image_path: Path,
        out_path: Path,
        tail_image_path: Path | None = None,
        prompt: str | None = None,
        cfg_scale: float | None = None,
    ) -> Path:
        """High-motion image->video (Kling): the character dances, no lip-sync.

        ``tail_image_path`` sets the clip's END frame. Passing the same image as
        start and tail makes the motion return home for a seamless loop.
        ``prompt``/``cfg_scale`` override the defaults (dance mode passes a far
        more aggressive motion prompt + lower cfg for bigger movement).
        """
        ...


@runtime_checkable
class MotionTransfer(Protocol):
    def transfer(self, appearance_image: Path, motion_video: Path, out_path: Path) -> Path:
        """Motion transfer (MimicMotion): the character in ``appearance_image``
        performs the exact moves of ``motion_video``. Returns the clip path."""
        ...


@runtime_checkable
class VideoLipSyncer(Protocol):
    def sync_video(self, video_path: Path, audio_path: Path, out_path: Path) -> Path:
        """Map a mouth onto an already-moving video, synced to ``audio_path``."""
        ...


def _is_fake() -> bool:
    return settings.PROVIDER_MODE == "fake"


def get_vocal_separator() -> VocalSeparator:
    if _is_fake():
        from providers.fakes import FakeVocalSeparator  # noqa: PLC0415

        return FakeVocalSeparator()
    from providers.replicate import RealDemucsSeparator  # noqa: PLC0415

    return RealDemucsSeparator()


def get_caption_aligner() -> CaptionAligner:
    if _is_fake():
        from providers.fakes import FakeCaptionAligner  # noqa: PLC0415

        return FakeCaptionAligner()
    from providers.replicate import RealWhisperXAligner  # noqa: PLC0415

    return RealWhisperXAligner()


def get_background_generator() -> BackgroundGenerator:
    if _is_fake():
        from providers.fakes import FakeBackgroundGenerator  # noqa: PLC0415

        return FakeBackgroundGenerator()
    from providers.fal import RealFalBackgroundGenerator  # noqa: PLC0415

    return RealFalBackgroundGenerator()


def get_portrait_generator() -> PortraitGenerator:
    if _is_fake():
        from providers.fakes import FakePortraitGenerator  # noqa: PLC0415

        return FakePortraitGenerator()
    from providers.fal import RealFalPortraitGenerator  # noqa: PLC0415

    return RealFalPortraitGenerator()


def get_scene_generator() -> SceneGenerator:
    if _is_fake():
        from providers.fakes import FakeSceneGenerator  # noqa: PLC0415

        return FakeSceneGenerator()
    from providers.fal import RealFalSceneGenerator  # noqa: PLC0415

    return RealFalSceneGenerator()


def get_matter() -> Matter:
    if _is_fake():
        from providers.fakes import FakeMatter  # noqa: PLC0415

        return FakeMatter()
    from providers.matting import RealFalMatter  # noqa: PLC0415

    return RealFalMatter()


def get_animator() -> Animator:
    if _is_fake():
        from providers.fakes import FakeAnimator  # noqa: PLC0415

        return FakeAnimator()
    from providers.motion import RealKlingAnimator  # noqa: PLC0415

    return RealKlingAnimator()


def get_motion_transfer() -> MotionTransfer:
    if _is_fake():
        from providers.fakes import FakeMotionTransfer  # noqa: PLC0415

        return FakeMotionTransfer()
    from providers.motion_transfer import RealMimicMotion  # noqa: PLC0415

    return RealMimicMotion()


def get_video_lip_syncer() -> VideoLipSyncer:
    if _is_fake():
        from providers.fakes import FakeVideoLipSyncer  # noqa: PLC0415

        return FakeVideoLipSyncer()
    from providers.lipsync import RealSyncVideoLipSyncer  # noqa: PLC0415

    return RealSyncVideoLipSyncer()


def get_lip_syncer() -> LipSyncer:
    if _is_fake():
        from providers.fakes import FakeLipSyncer  # noqa: PLC0415

        return FakeLipSyncer()
    provider = settings.LIPSYNC_PROVIDER
    if provider == "omnihuman":
        from providers.lipsync import RealOmniHumanLipSyncer  # noqa: PLC0415

        return RealOmniHumanLipSyncer()
    if provider == "hedra":
        from providers.lipsync import RealHedraLipSyncer  # noqa: PLC0415

        return RealHedraLipSyncer()
    if provider == "sync":
        from providers.lipsync import RealSyncLipSyncer  # noqa: PLC0415

        return RealSyncLipSyncer()
    if provider == "magic_hour":
        from providers.lipsync import RealMagicHourLipSyncer  # noqa: PLC0415

        return RealMagicHourLipSyncer()
    raise ProviderConfigError(
        f"Unknown LIPSYNC_PROVIDER {provider!r}; expected omnihuman | hedra | sync | magic_hour."
    )
