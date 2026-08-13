import re

import pandas as pd
import nltk
from word2number import w2n

# Downloaind models
nltk.download('punkt')
nltk.download('averaged_perceptron_tagger')

# Parse the sentence using NLP to get keywords and amount
def getEntry(text):
    # Tokenize using nltk
    tokenized = nltk.word_tokenize(text)
    # Perform POS Tagging using Penn Treebank codeset
    pos = nltk.pos_tag(tokenized)
    entry = identifyEntry(pos)
    return entry

def identifyEntry(tags):
    nouns = list()
    amount = None
    # Only keep nouns and cardinal number.
    # Noun is recognized by NNS, NN, NP, NPS
    # So we see if first letter is N, if yes, we add it to the tags.
    for item in tags:
        value, tag = item
        value = str(value)
        if tag.startswith('N'):
            nouns.append(value)
        if tag == 'CD':
            amount = value
    return nouns, amount


# --- Robust amount extraction ---------------------------------------------
# The original identifyEntry() above only catches the *first* CD-tagged
# token anywhere in the sentence, which misses spelled-out numbers entirely
# ("twenty dollars" has no CD token) and can grab the wrong number in a
# sentence with more than one. These functions layer digit-based currency
# patterns and spelled-out-number parsing on top, falling back to the
# original CD-tag behavior last so existing plain-digit sentences keep
# working exactly as before.

_CURRENCY_PATTERNS = [
    re.compile(r'\$\s?(\d+(?:\.\d{1,2})?)', re.IGNORECASE),
    re.compile(
        r'(\d+(?:\.\d{1,2})?)\s*dollars?(?:\s+(?:and\s+)?(\d{1,2})\s*cents?)?\b',
        re.IGNORECASE,
    ),
    re.compile(r'(\d+(?:\.\d{1,2})?)\s*bucks?\b', re.IGNORECASE),
]

_NUMBER_WORD = (
    r'(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
    r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|'
    r'thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|and)'
)
_NUMBER_PHRASE = rf'(?:{_NUMBER_WORD}(?:[\s-]+{_NUMBER_WORD})*)'
_WORDS_AMOUNT_RE = re.compile(
    rf'\b({_NUMBER_PHRASE})\s+dollars?\b(?:\s+(?:and\s+)?({_NUMBER_PHRASE})\s+cents?\b)?',
    re.IGNORECASE,
)

_FILLER_LEAD_RE = re.compile(
    r'^\s*(i\s+)?(spent|spend|paid|pay|bought|buy)\b\s*', re.IGNORECASE
)
_FILLER_TRAIL_RE = re.compile(r'\s+(on|for|and)\s*$', re.IGNORECASE)
_LEADING_CONNECTOR_RE = re.compile(r'^(on|for|and)\s+', re.IGNORECASE)
_STRAY_CURRENCY_WORDS_RE = re.compile(r'\b(dollars?|cents?|bucks?)\b', re.IGNORECASE)


def extract_amount_regex(text):
    """Digit-based currency patterns: "$12.50", "12 dollars(and 50 cents)?",
    "12 bucks". Returns (amount, (start, end) span in text) or (None, None)."""
    for pattern in _CURRENCY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        base = float(match.group(1))
        cents = 0.0
        if match.lastindex and match.lastindex >= 2 and match.group(2):
            cents = float(match.group(2)) / 100
        return round(base + cents, 2), match.span()
    return None, None


def extract_amount_words(text):
    """Spelled-out numbers: "twenty dollars", "forty five dollars and fifty
    cents". Returns (amount, span) or (None, None)."""
    match = _WORDS_AMOUNT_RE.search(text)
    if not match:
        return None, None
    try:
        dollars = w2n.word_to_num(match.group(1))
        cents = w2n.word_to_num(match.group(2)) if match.group(2) else 0
        return round(dollars + cents / 100, 2), match.span()
    except ValueError:
        return None, None


def extract_amount_cardinal(text):
    """Last-resort fallback: the original CD-tag logic, unchanged behavior
    for plain-digit sentences it already handled correctly."""
    _, amount_str = getEntry(text)
    if amount_str is None:
        return None, None
    try:
        amount = float(amount_str)
    except ValueError:
        return None, None
    idx = text.lower().find(str(amount_str).lower())
    span = (idx, idx + len(amount_str)) if idx != -1 else None
    return amount, span


def extract_amount(text):
    """Tries digit-based currency patterns, then spelled-out numbers, then
    the legacy CD-tag fallback, in that order. Returns (amount, span) for
    the first one that finds something, or (None, None)."""
    for fn in (extract_amount_regex, extract_amount_words, extract_amount_cardinal):
        amount, span = fn(text)
        if amount is not None:
            return amount, span
    return None, None


def clean_description(text, amount_span):
    """Strips the matched amount phrase (if any) and lightweight filler
    ("i spent", "paid for", trailing "on"/"for") out of the transcript, so
    what's left is natural text usable both as the user-facing description
    and as the categorizer's input -- not a sparse noun-only bag."""
    if amount_span:
        text = text[: amount_span[0]] + ' ' + text[amount_span[1]:]
    text = _STRAY_CURRENCY_WORDS_RE.sub('', text)
    text = _FILLER_LEAD_RE.sub('', text)
    text = _FILLER_TRAIL_RE.sub('', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = _LEADING_CONNECTOR_RE.sub('', text).strip()
    # Whisper (unlike the old engine) punctuates its output, which can leave
    # a stray leading/trailing mark once the amount phrase is cut out.
    text = text.strip(' .,!?;:')
    return text

