from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from .. import models, schemas, security
from ..services import categorizer

router = APIRouter(prefix="/categorize", tags=["categorize"])


@router.post("", response_model=schemas.CategorizeResponse)
async def categorize_text(
    payload: schemas.CategorizeRequest,
    current_user: models.User = Depends(security.get_current_user),
):
    # BERT inference is CPU-bound/blocking -- run it off the event loop so one
    # categorization call doesn't stall every other concurrent request.
    category, confidence = await run_in_threadpool(categorizer.categorize, payload.text)
    return schemas.CategorizeResponse(category=category, confidence=confidence)
