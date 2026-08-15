"""Real-time voice capture over WebSocket.

Protocol (server perspective):

    <- connect  /ws/voice?token=<access token>
    -> {"type": "ready"}
    <- binary audio chunks (webm/opus from MediaRecorder)
    -> {"type": "partial", "transcript": "..."}   ... repeatedly
    <- {"action": "finalize"}
    -> {"type": "final", "result": {...}}

Partial transcripts are previews and will be replaced; the ``final`` frame is
the authoritative parse.

**Nothing here is saved.** The ``final`` frame is a proposal: the client shows
it for review and the user commits it with ``POST /voice/confirm``, which is
the only write path for voice. Persisting on finalize would both rob the user
of the chance to fix a misheard amount or a wrong category, and -- since the
client also calls ``/voice/confirm`` -- write the transaction twice.

Auth note: browsers cannot set an Authorization header on a WebSocket
handshake, so the access token arrives as a query parameter. That puts it in
server access logs, which is why access tokens are short-lived (30 minutes)
and refresh tokens are never accepted here.
"""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..core.database import SessionLocal
from ..core.deps import get_current_user_ws
from ..core.logging import get_logger
from ..schemas.voice import WSError, WSMessageType, WSPartial
from ..services import pipeline, speech

router = APIRouter(tags=["voice"])
log = get_logger(__name__)

# Transcribe a preview roughly every this many bytes of buffered audio.
# Opus at typical MediaRecorder bitrates is ~4KB/s, so this is about a
# preview every 8 seconds -- frequent enough to feel live, infrequent enough
# that previews don't queue up behind each other.
PARTIAL_INTERVAL_BYTES = 32_000
MAX_TOTAL_BYTES = 10 * 1024 * 1024

CLOSE_UNAUTHORIZED = 1008  # policy violation
CLOSE_TOO_LARGE = 1009


@router.websocket("/ws/voice")
async def voice_socket(websocket: WebSocket, token: str | None = None) -> None:
    await websocket.accept()

    async with SessionLocal() as db:
        user = await get_current_user_ws(db, token)
        if user is None:
            await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Invalid or missing token")
            return

        await websocket.send_json({"type": WSMessageType.READY.value})

        buffer = bytearray()
        last_partial_at = 0

        try:
            while True:
                message = await websocket.receive()

                if message["type"] == "websocket.disconnect":
                    break

                # --- audio chunk ---------------------------------------
                if (chunk := message.get("bytes")) is not None:
                    buffer.extend(chunk)

                    if len(buffer) > MAX_TOTAL_BYTES:
                        await websocket.close(code=CLOSE_TOO_LARGE, reason="Recording too long")
                        return

                    if len(buffer) - last_partial_at >= PARTIAL_INTERVAL_BYTES:
                        last_partial_at = len(buffer)
                        # Decoding a mid-stream buffer often fails because it
                        # isn't a complete container yet; that returns "" and
                        # we simply skip this preview.
                        if partial := await speech.transcribe_stream_chunk(bytes(buffer)):
                            await websocket.send_json(
                                WSPartial(transcript=partial).model_dump(mode="json")
                            )
                    continue

                # --- control frame -------------------------------------
                if (text := message.get("text")) is None:
                    continue

                try:
                    action = json.loads(text).get("action")
                except json.JSONDecodeError:
                    await websocket.send_json(
                        WSError(detail="Expected a JSON control frame").model_dump(mode="json")
                    )
                    continue

                if action == "cancel":
                    break

                if action != "finalize":
                    continue

                if not buffer:
                    await websocket.send_json(
                        WSError(detail="No audio received").model_dump(mode="json")
                    )
                    continue

                await _finalize(websocket, db, user, bytes(buffer))
                buffer.clear()
                last_partial_at = 0

        except WebSocketDisconnect:
            log.info("ws.client_disconnected", user_id=user.id)
        except Exception as exc:
            log.error("ws.unhandled_error", user_id=user.id, error=str(exc), exc_info=True)
            if websocket.client_state is WebSocketState.CONNECTED:
                await websocket.send_json(
                    WSError(detail="Something went wrong processing that recording").model_dump(
                        mode="json"
                    )
                )
        finally:
            if websocket.client_state is WebSocketState.CONNECTED:
                await websocket.close()


async def _finalize(websocket: WebSocket, db, user, audio: bytes) -> None:  # type: ignore[no-untyped-def]
    """Transcribe the full recording and parse it. Writes nothing.

    ``process_transcript`` may create a Merchant row as a side effect of
    resolving the name, so the session is rolled back afterwards -- a recording
    the user ends up discarding should leave no trace.
    """
    transcript = await speech.transcribe_audio_bytes(audio, suffix=".webm")
    if not transcript:
        await websocket.send_json(
            WSError(detail="Could not make out any speech in that recording").model_dump(
                mode="json"
            )
        )
        return

    parsed, _merchant = await pipeline.process_transcript(
        transcript, db=db, default_currency=user.currency
    )
    await db.rollback()

    await websocket.send_json(
        {"type": WSMessageType.FINAL.value, "result": parsed.model_dump(mode="json")}
    )
