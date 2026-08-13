"""Claude-backed structured extraction, used only as a fallback.

The deterministic layer in ``nlp_extract`` handles the common shapes. What
reaches here is the messy tail -- "grabbed a couple coffees with Sam and put
it on my card, think it came to about thirty five" -- where regexes stop being
the right tool.

Design notes:

* **Strictly optional.** With no API key configured, ``extract`` returns None
  and the caller keeps the deterministic result. The feature degrades; it
  never breaks the request.
* **Schema-constrained.** ``messages.parse`` validates the response against
  the same Pydantic model the rest of the pipeline uses, so the two paths
  cannot drift apart.
* **Low effort.** This is a short extraction, not a reasoning problem. Note
  that thinking is left on -- disabling it on Opus 5 has known failure modes,
  and low effort is the cheaper lever anyway.
"""

from datetime import date

from ..core.config import get_settings
from ..core.logging import get_logger
from ..schemas.voice import ExtractedTransaction

settings = get_settings()
log = get_logger(__name__)

_client: object | None = None

SYSTEM_PROMPT = """\
You extract structured expense data from voice transcripts of someone \
recording a purchase they made.

The transcript comes from speech-to-text, so expect no punctuation, \
homophone errors, and spoken number idioms. In speech "twelve fifty" means \
12.50, not 62.

Rules:
- amount: the total the speaker paid, as a positive number. Null if no amount \
was stated. Do not infer an amount from a quantity ("two coffees" is not 2).
- currency: ISO 4217. Infer from any symbol or word said; otherwise use the \
user's default, given below.
- merchant: the store or payee, if named. Null otherwise. Do not invent one.
- description: a short natural phrase describing the purchase, without the \
amount or filler words like "I spent".
- date: only if the speaker stated one. Resolve relative mentions against \
today's date, given below. Null if unstated.

Report only what was actually said. A null field is correct and useful; a \
guessed one is not."""


def _get_client() -> object | None:
    global _client
    if not settings.llm_available:
        return None
    if _client is None:
        from anthropic import AsyncAnthropic

        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def extract(
    transcript: str,
    *,
    default_currency: str = "USD",
    today: date | None = None,
) -> ExtractedTransaction | None:
    """Parse a transcript into structured fields, or None if unavailable."""
    client = _get_client()
    if client is None or not transcript.strip():
        return None

    today = today or date.today()

    try:
        response = await client.messages.parse(  # type: ignore[attr-defined]
            model=settings.anthropic_model,
            max_tokens=1024,
            output_config={"effort": "low"},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # The prompt is byte-identical on every call, so caching it
                    # makes the fallback path meaningfully cheaper.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Today is {today.isoformat()}. "
                        f"The user's default currency is {default_currency}.\n\n"
                        f"Transcript: {transcript}"
                    ),
                }
            ],
            output_format=ExtractedTransaction,
        )
    except Exception as exc:
        # Network failure, rate limit, bad key -- all recoverable, because the
        # deterministic result is still there.
        log.warning("llm_extract.failed", error=str(exc), error_type=type(exc).__name__)
        return None

    # Opus 5's safety classifiers can decline a request outright. Checking
    # stop_reason before touching content matters: on a refusal the content
    # list is empty, so indexing into it would raise.
    if getattr(response, "stop_reason", None) == "refusal":
        log.warning("llm_extract.refused", detail=str(getattr(response, "stop_details", None)))
        return None

    parsed = getattr(response, "parsed_output", None)
    if parsed is None:
        return None

    log.info(
        "llm_extract.succeeded",
        has_amount=parsed.amount is not None,
        has_merchant=parsed.merchant is not None,
    )
    return parsed
