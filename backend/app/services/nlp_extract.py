import nlp


def extract_description_and_amount(transcript: str) -> tuple[str, float | None]:
    """Amount: digit currency patterns -> spelled-out-number fallback ->
    legacy NLTK CD-tag fallback (nlp.extract_amount). Description: the
    transcript with the matched amount phrase and simple filler stripped out
    (nlp.clean_description) -- not a noun-only bag, which is a poor style
    match for both user-facing text and the categorizer's kNN index.
    """
    amount, span = nlp.extract_amount(transcript)
    description = nlp.clean_description(transcript, span)
    if not description:
        nouns, _ = nlp.getEntry(transcript)
        description = " ".join(nouns) or transcript
    return description, amount
