from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import models, schemas, security
from ..services import categorizer, nlp_extract, speech

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/transcribe", response_model=schemas.VoiceTranscribeResponse)
async def transcribe(
    audio: UploadFile = File(...),
    current_user: models.User = Depends(security.get_current_user),
):
    """One round trip: transcribe -> extract description/amount -> categorize."""
    audio_bytes = await audio.read()
    transcript = await run_in_threadpool(speech.transcribe_audio_bytes, audio_bytes)

    if not transcript:
        return schemas.VoiceTranscribeResponse(
            transcript=None, description="", amount=None, category=None, confidence=0.0
        )

    description, amount = nlp_extract.extract_description_and_amount(transcript)

    category, confidence = None, 0.0
    if description:
        category, confidence = await run_in_threadpool(categorizer.categorize, description)

    return schemas.VoiceTranscribeResponse(
        transcript=transcript,
        description=description,
        amount=amount,
        category=category,
        confidence=confidence,
    )
