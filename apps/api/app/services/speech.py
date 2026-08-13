"""Speech-to-text via faster-whisper (CTranslate2).

Runs locally: no API key, no per-request cost, no audio leaving the machine.

Device selection is automatic. On CUDA the model runs ``int8_float16``, which
fits ``small.en`` comfortably in 6GB and is both faster and more accurate than
the CPU ``base.en`` this replaces. Without a GPU it falls back to CPU ``int8``.
"""

import os
import tempfile
from typing import Any

import anyio
from faster_whisper import WhisperModel

from ..core.config import get_settings
from ..core.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

_model: WhisperModel | None = None


def _resolve_device() -> tuple[str, str]:
    """Return ``(device, compute_type)``.

    torch is imported lazily and defensively -- a CPU-only install is a
    supported configuration, not an error.
    """
    configured = settings.whisper_device
    if configured == "cpu":
        return "cpu", "int8"
    if configured == "cuda":
        return "cuda", "int8_float16"

    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "int8_float16"
    except Exception as exc:
        log.debug("speech.cuda_probe_failed", error=str(exc))
    return "cpu", "int8"


def get_model() -> WhisperModel:
    """Load once per process; inference is read-only so sharing is safe."""
    global _model
    if _model is None:
        device, compute_type = _resolve_device()
        log.info(
            "speech.loading_model",
            model=settings.whisper_model_size,
            device=device,
            compute_type=compute_type,
        )
        try:
            _model = WhisperModel(
                settings.whisper_model_size, device=device, compute_type=compute_type
            )
        except Exception as exc:
            # A CUDA load can fail at runtime for reasons a capability probe
            # won't catch (missing cuDNN, mismatched driver). Falling back to
            # CPU keeps the feature working instead of 500ing every request.
            if device == "cuda":
                log.warning("speech.cuda_load_failed_falling_back", error=str(exc))
                _model = WhisperModel(
                    settings.whisper_model_size, device="cpu", compute_type="int8"
                )
            else:
                raise
    return _model


def warm_up() -> None:
    get_model()


def _transcribe_file(path: str, **kwargs: Any) -> str:
    segments, _info = get_model().transcribe(path, language="en", **kwargs)
    # `segments` is a lazy generator -- transcription only actually runs as it
    # is consumed, so this join is where the work happens.
    return " ".join(segment.text.strip() for segment in segments).strip()


async def transcribe_audio_bytes(audio_bytes: bytes, suffix: str = ".wav") -> str:
    """Transcribe an audio clip. Returns "" when nothing intelligible was said.

    Whisper needs a file path, so the bytes go to a per-request temp file --
    per-request specifically, so concurrent uploads can't clobber each other.
    Transcription is CPU/GPU-bound and runs in a worker thread to keep the
    event loop responsive.
    """
    if not audio_bytes:
        return ""

    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(audio_bytes)
        return await anyio.to_thread.run_sync(_transcribe_file, path)
    finally:
        os.unlink(path)


async def transcribe_stream_chunk(audio_bytes: bytes, suffix: str = ".webm") -> str:
    """Transcribe a partial buffer for live WebSocket previews.

    Uses a greedy single-beam pass: interim text is going to be replaced
    moments later, so latency matters far more than accuracy here. The final
    transcript is produced by ``transcribe_audio_bytes`` over the whole
    recording.
    """
    if not audio_bytes:
        return ""

    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(audio_bytes)
        return await anyio.to_thread.run_sync(
            lambda: _transcribe_file(path, beam_size=1, best_of=1, condition_on_previous_text=False)
        )
    except Exception as exc:
        # A partial buffer often isn't a decodable container yet. That's
        # expected mid-stream, not an error worth surfacing.
        log.debug("speech.partial_decode_failed", error=str(exc))
        return ""
    finally:
        os.unlink(path)
