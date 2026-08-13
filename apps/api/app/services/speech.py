import os
import tempfile

from faster_whisper import WhisperModel

from ..config import settings

# Module-level singleton, same pattern as services/categorizer.py: the
# Whisper model is loaded once at process startup (via warm_up(), called
# from the FastAPI lifespan handler) and reused across every request rather
# than reloaded per call.
_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        # int8 quantization keeps CPU inference fast with a small accuracy
        # tradeoff -- appropriate for a demo/dev deployment with no GPU.
        _model = WhisperModel(settings.whisper_model_size, device="cpu", compute_type="int8")
    return _model


def warm_up() -> None:
    get_model()


def transcribe_audio_bytes(wav_bytes: bytes) -> str | None:
    """Transcribe a WAV audio clip given as raw bytes using a local Whisper
    model (replaces the earlier free Google Web Speech API, which had no
    confidence scores, no domain adaptation, and was a hard accuracy
    ceiling). Runs fully offline, no API key or per-request cost.

    Writes to a per-request tempfile so concurrent requests don't clobber
    each other's recordings.
    """
    fd, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(wav_bytes)
        segments, _ = get_model().transcribe(path, language="en")
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text.lower() if text else None
    finally:
        os.remove(path)
