"""Deterministic transcript -> structured transaction extraction.

Runs before any LLM call. It is fast, free, offline, and handles the majority
of real utterances ("twelve fifty at starbucks", "$40 on groceries"). Only
what this layer cannot parse gets escalated to the model in ``llm_extract``.

Ported from the original ``nlp.py`` with three changes:

* **NLTK is gone.** Its only remaining job was a part-of-speech pass to find a
  bare cardinal number, which a regex does better -- and importing it ran
  ``nltk.download()`` on every process start.
* **Currencies are explicit.** The old code parsed USD exclusively ("$",
  "dollars", "bucks") while the UI rendered "Rs.", so every rupee amount was
  mislabeled. Symbols and words now map to an ISO code, with the user's own
  currency as the default.
* **Merchants are extracted**, so "at starbucks" populates a real field
  instead of being left inside the description blob.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from word2number import w2n

from ..schemas.voice import ExtractionMethod

# --------------------------------------------------------------------------
# currency
# --------------------------------------------------------------------------

# Symbol/word -> ISO 4217. Order matters for the alternation below: longer
# spellings must precede their own prefixes so "rupees" isn't matched as "rs".
CURRENCY_TOKENS: dict[str, str] = {
    "$": "USD",
    "dollars": "USD",
    "dollar": "USD",
    "bucks": "USD",
    "buck": "USD",
    "usd": "USD",
    "₹": "INR",
    "rupees": "INR",
    "rupee": "INR",
    "inr": "INR",
    "rs.": "INR",
    "rs": "INR",
    "€": "EUR",
    "euros": "EUR",
    "euro": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "pounds": "GBP",
    "pound": "GBP",
    "quid": "GBP",
    "gbp": "GBP",
}

_SYMBOLS = r"[$₹€£]"
_CURRENCY_WORDS = "|".join(
    re.escape(word)
    for word in sorted((w for w in CURRENCY_TOKENS if not re.match(_SYMBOLS, w)), key=len, reverse=True)
)

# --------------------------------------------------------------------------
# amount patterns
# --------------------------------------------------------------------------

# The comma-grouped branch requires at least one comma group (`+`, not `*`).
# With `*` it matches the leading "120" of "1200" and stops there -- the
# alternation never reaches the plain-digits branch, so every amount over 999
# written without separators was silently truncated.
_DIGITS = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"

_AMOUNT_PATTERNS: list[re.Pattern[str]] = [
    # "$12.50", "₹1,200"
    re.compile(rf"({_SYMBOLS})\s?({_DIGITS})", re.IGNORECASE),
    # "12 dollars and 50 cents", "1,200 rupees"
    re.compile(
        rf"({_DIGITS})\s*({_CURRENCY_WORDS})\b(?:\s+(?:and\s+)?(\d{{1,2}})\s*cents?\b)?",
        re.IGNORECASE,
    ),
]

# Currency written *before* the number: "Rs 250", "USD 40", "rupees 250".
# Needs its own pattern because the group order is reversed.
_PREFIX_CURRENCY_RE = re.compile(rf"\b({_CURRENCY_WORDS})\s*({_DIGITS})\b", re.IGNORECASE)

_NUMBER_WORD = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|and)"
)
_NUMBER_PHRASE = rf"(?:{_NUMBER_WORD}(?:[\s-]+{_NUMBER_WORD})*)"

# "twenty dollars", "forty five rupees and fifty cents"
_WORDS_AMOUNT_RE = re.compile(
    rf"\b({_NUMBER_PHRASE})\s+({_CURRENCY_WORDS})\b"
    rf"(?:\s+(?:and\s+)?({_NUMBER_PHRASE})\s+cents?\b)?",
    re.IGNORECASE,
)

# Bare number with no currency marker at all -- "spent 40 on groceries".
# Last resort, and deliberately anchored to a spend verb or preposition so it
# doesn't grab the "2" out of "2 coffees".
_BARE_AMOUNT_RE = re.compile(
    rf"\b(?:spent|spend|paid|pay|cost|costs|for|about|around)\s+({_DIGITS})\b",
    re.IGNORECASE,
)

# Spelled-out number with no currency word -- "spent twelve fifty at ...".
_BARE_WORDS_AMOUNT_RE = re.compile(
    rf"\b(?:spent|spend|paid|pay|cost|costs|for|about|around)\s+({_NUMBER_PHRASE})\b",
    re.IGNORECASE,
)

_TENS_WORDS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
_UNIT_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen",
}


def _parse_spoken_amount(phrase: str) -> Decimal | None:
    """Parse a spelled-out amount, honouring the spoken price idiom.

    ``word_to_num`` is purely additive, so it reads "twelve fifty" as 62 --
    but a speaker saying it means 12.50. The two-token shapes disambiguate:

        <tens> <unit>          "twenty five"   -> 25    (additive)
        <unit|teen> <tens>     "twelve fifty"  -> 12.50 (price idiom)
        <tens> <tens>          "fifty twenty"  -> 50.20 (price idiom)

    Anything else (single words, "hundred"/"thousand" forms) falls through to
    word_to_num, which handles them correctly.
    """
    tokens = re.split(r"[\s-]+", phrase.lower().strip())
    tokens = [t for t in tokens if t and t != "and"]

    if len(tokens) == 2:
        first, second = tokens
        if second in _TENS_WORDS and (first in _UNIT_WORDS or first in _TENS_WORDS):
            try:
                return Decimal(w2n.word_to_num(first)) + Decimal(w2n.word_to_num(second)) / 100
            except ValueError:
                return None

    try:
        return Decimal(w2n.word_to_num(phrase))
    except ValueError:
        return None

# --------------------------------------------------------------------------
# description / merchant cleanup
# --------------------------------------------------------------------------

_MERCHANT_RE = re.compile(
    r"\b(?:at|from|to|in)\s+((?:[A-Z][\w'&-]*|[a-z][\w'&-]*)(?:\s+[A-Z][\w'&-]*)*)",
)
_FILLER_LEAD_RE = re.compile(r"^\s*(i\s+)?(just\s+)?(spent|spend|paid|pay|bought|buy)\b\s*", re.IGNORECASE)
_FILLER_TRAIL_RE = re.compile(
    r"[\s,]+(on|for|and|at|from|about|around|roughly|approximately)\s*$", re.IGNORECASE
)
_LEADING_CONNECTOR_RE = re.compile(r"^(on|for|and|at|from)\s+", re.IGNORECASE)
_STRAY_CURRENCY_RE = re.compile(rf"\b({_CURRENCY_WORDS}|cents?)\b|{_SYMBOLS}", re.IGNORECASE)

# --------------------------------------------------------------------------
# relative dates
# --------------------------------------------------------------------------

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_RELATIVE_DATE_RE = re.compile(
    r"\b(today|yesterday|last\s+night|this\s+morning|"
    r"last\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Extraction:
    """What the deterministic layer managed to pull out of a transcript."""

    amount: Decimal | None
    currency: str
    description: str
    merchant: str | None
    date: date
    method: ExtractionMethod


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def extract_amount(text: str, default_currency: str) -> tuple[Decimal | None, str, tuple[int, int] | None, ExtractionMethod]:
    """Return ``(amount, currency, matched span, method)``.

    Tries digit+currency patterns, then spelled-out numbers, then a bare
    number anchored to a spend verb.
    """
    for pattern in _AMOUNT_PATTERNS:
        if not (match := pattern.search(text)):
            continue
        groups = match.groups()
        # Pattern 1 is (symbol, digits); pattern 2 is (digits, word, cents?).
        if groups[0] and re.match(_SYMBOLS, groups[0]):
            currency = CURRENCY_TOKENS[groups[0]]
            amount = _to_decimal(groups[1])
        else:
            currency = CURRENCY_TOKENS.get(groups[1].lower().rstrip("."), default_currency)
            amount = _to_decimal(groups[0])
            if amount is not None and len(groups) > 2 and groups[2]:
                amount += Decimal(groups[2]) / 100
        if amount is not None:
            return amount, currency, match.span(), ExtractionMethod.REGEX

    # "Rs 250", "USD 40" -- currency word ahead of the number.
    if match := _PREFIX_CURRENCY_RE.search(text):
        currency = CURRENCY_TOKENS.get(match.group(1).lower().rstrip("."), default_currency)
        if (amount := _to_decimal(match.group(2))) is not None:
            return amount, currency, match.span(), ExtractionMethod.REGEX

    if match := _WORDS_AMOUNT_RE.search(text):
        whole = _parse_spoken_amount(match.group(1))
        if whole is not None:
            currency = CURRENCY_TOKENS.get(match.group(2).lower().rstrip("."), default_currency)
            cents = _parse_spoken_amount(match.group(3)) if match.group(3) else None
            amount = whole + (cents / 100 if cents is not None else Decimal(0))
            return amount, currency, match.span(), ExtractionMethod.WORDS

    if match := _BARE_AMOUNT_RE.search(text):
        if (amount := _to_decimal(match.group(1))) is not None:
            # Span covers only the number, not the anchoring verb -- removing
            # "spent" here would mangle the description.
            return amount, default_currency, match.span(1), ExtractionMethod.REGEX

    # "spent twelve fifty at Starbucks" -- spelled out, no currency word.
    if match := _BARE_WORDS_AMOUNT_RE.search(text):
        if (amount := _parse_spoken_amount(match.group(1))) is not None:
            return amount, default_currency, match.span(1), ExtractionMethod.WORDS

    return None, default_currency, None, ExtractionMethod.NONE


def extract_merchant(text: str) -> tuple[str | None, tuple[int, int] | None]:
    """Pull a payee out of an "at/from <name>" phrase."""
    if not (match := _MERCHANT_RE.search(text)):
        return None, None
    merchant = match.group(1).strip(" .,!?")
    # Single common words after "at"/"in" are usually not merchants
    # ("at home", "in cash"), so require either capitalisation or length.
    if len(merchant) < 3 or merchant.lower() in {"home", "work", "cash", "the", "my"}:
        return None, None
    return merchant, match.span()


def extract_date(text: str, today: date | None = None) -> tuple[date, tuple[int, int] | None]:
    """Resolve a relative date mention, returning it with its matched span.

    The span matters: without it the phrase stays in the description, so
    "spent 40 on groceries yesterday" gets stored as "groceries yesterday"
    and every later transaction for the same thing looks like a new merchant.
    """
    today = today or date.today()
    if not (match := _RELATIVE_DATE_RE.search(text)):
        return today, None

    phrase = re.sub(r"\s+", " ", match.group(1).lower())
    span = match.span()

    if phrase in {"today", "this morning"}:
        return today, span
    if phrase in {"yesterday", "last night"}:
        return today - timedelta(days=1), span
    if phrase.startswith("last "):
        weekday = _WEEKDAYS.get(phrase.removeprefix("last ").strip())
        if weekday is not None:
            # Walk back to the most recent occurrence of that weekday.
            delta = (today.weekday() - weekday) % 7 or 7
            return today - timedelta(days=delta), span
    return today, span


def clean_description(text: str, *spans: tuple[int, int] | None) -> str:
    """Remove matched spans and filler, leaving natural text.

    The result feeds both the user-facing description and the categorizer, so
    it stays a readable phrase rather than a bag of nouns -- the exemplars in
    Qdrant are phrases, and matching like against like measurably helps.
    """
    for span in sorted((s for s in spans if s), key=lambda s: s[0], reverse=True):
        text = text[: span[0]] + " " + text[span[1] :]

    text = _STRAY_CURRENCY_RE.sub("", text)
    text = _FILLER_LEAD_RE.sub("", text)
    text = _FILLER_TRAIL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _LEADING_CONNECTOR_RE.sub("", text).strip()
    # Whisper punctuates its output, so cutting a span out can leave a stray
    # mark at either end.
    return text.strip(" .,!?;:-")


def extract(transcript: str, default_currency: str = "USD", today: date | None = None) -> Extraction:
    """Full deterministic pass over a transcript."""
    amount, currency, amount_span, method = extract_amount(transcript, default_currency)
    merchant, _merchant_span = extract_merchant(transcript)
    when, date_span = extract_date(transcript, today)

    # The merchant span is deliberately NOT stripped: "coffee at Starbucks"
    # reads better as a description than a bare "coffee", and the merchant is
    # stored separately anyway.
    description = clean_description(transcript, amount_span, date_span)
    if not description:
        description = merchant or transcript.strip()

    return Extraction(
        amount=amount,
        currency=currency,
        description=description,
        merchant=merchant,
        date=when,
        method=method,
    )
