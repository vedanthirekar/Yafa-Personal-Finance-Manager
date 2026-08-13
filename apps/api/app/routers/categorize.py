from fastapi import APIRouter

from ..core.deps import CurrentUser
from ..schemas import CategorizeRequest, CategorizeResponse
from ..services import categorizer

router = APIRouter(prefix="/categorize", tags=["categorize"])


@router.post("", response_model=CategorizeResponse)
async def categorize_text(
    payload: CategorizeRequest, current_user: CurrentUser
) -> CategorizeResponse:
    """Semantically categorize a free-text description.

    Embeds the text with a BERT bi-encoder and takes a similarity-weighted
    vote over its nearest labeled neighbours in Qdrant. A null category means
    nothing scored above the confidence threshold -- the caller should ask
    rather than guess.
    """
    category, confidence, alternatives = await categorizer.categorize(payload.text)
    return CategorizeResponse(category=category, confidence=confidence, alternatives=alternatives)
