from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from ..core.deps import CurrentUser, DbSession
from ..models import TransactionSource
from ..schemas import TransactionOut, VoiceTranscribeResponse
from ..services import pipeline, speech

router = APIRouter(prefix="/voice", tags=["voice"])

# Whisper handles far longer clips, but a spoken expense is a few seconds.
# A cap keeps a large upload from occupying a GPU slot for minutes.
MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.post("/transcribe", response_model=VoiceTranscribeResponse)
async def transcribe(
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(..., description="Audio clip (wav/webm/m4a/ogg)"),
    persist: bool = Query(False, description="Also save the parsed transaction"),
) -> VoiceTranscribeResponse:
    """Transcribe an audio clip and parse it into a structured transaction.

    Non-streaming counterpart to ``WS /ws/voice``. Returns the parsed result
    without saving unless ``persist=true`` -- the web app previews first so
    the user can correct a misheard amount before it's committed.
    """
    audio = await file.read()
    if not audio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty audio upload")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Audio exceeds {MAX_AUDIO_BYTES // (1024 * 1024)}MB limit",
        )

    suffix = (
        f".{file.filename.rsplit('.', 1)[-1]}" if file.filename and "." in file.filename else ".wav"
    )
    transcript = await speech.transcribe_audio_bytes(audio, suffix=suffix)
    if not transcript:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Could not make out any speech in that recording",
        )

    parsed, merchant = await pipeline.process_transcript(
        transcript, db=db, default_currency=current_user.currency
    )

    if persist:
        await pipeline.persist_transaction(
            db,
            user_id=current_user.id,
            parsed=parsed,
            merchant=merchant,
            source=TransactionSource.VOICE,
        )

    return parsed


@router.post("/confirm", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def confirm(
    parsed: VoiceTranscribeResponse, db: DbSession, current_user: CurrentUser
) -> TransactionOut:
    """Save a previewed transaction, after any edits the user made.

    Takes the response body back rather than re-transcribing, so corrections
    made in the UI survive.
    """
    if parsed.amount is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "An amount is required before saving",
        )

    merchant = await pipeline.resolve_merchant(db, parsed.merchant)
    transaction = await pipeline.persist_transaction(
        db,
        user_id=current_user.id,
        parsed=parsed,
        merchant=merchant,
        source=TransactionSource.VOICE,
    )

    from .transactions import _get_owned, _to_out

    return _to_out(await _get_owned(db, transaction.id, current_user.id))
