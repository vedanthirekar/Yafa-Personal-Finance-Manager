"""Tests for deterministic transcript extraction.

This layer handles the majority of real utterances without an LLM call, so
its edge cases are worth pinning down precisely -- especially the spoken price
idiom, which the underlying word2number library gets wrong.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.schemas.voice import ExtractionMethod
from app.services.nlp_extract import (
    _parse_spoken_amount,
    clean_description,
    extract,
    extract_amount,
    extract_date,
    extract_merchant,
)

# A Thursday, so "last friday" is unambiguously 6 days earlier.
TODAY = date(2026, 8, 13)


class TestSpokenAmounts:
    @pytest.mark.parametrize(
        ("phrase", "expected"),
        [
            # The price idiom: word2number reads "twelve fifty" additively as
            # 62. A speaker means 12.50.
            ("twelve fifty", Decimal("12.50")),
            ("fifteen twenty", Decimal("15.20")),
            ("fifty twenty", Decimal("50.20")),
            # Additive forms must keep working.
            ("twenty five", Decimal(25)),
            ("forty five", Decimal(45)),
            ("ninety nine", Decimal(99)),
            # Single words and scale words fall through to word2number.
            ("twelve", Decimal(12)),
            ("two hundred", Decimal(200)),
        ],
    )
    def test_parses_spoken_amount(self, phrase: str, expected: Decimal) -> None:
        assert _parse_spoken_amount(phrase) == expected

    def test_returns_none_for_non_numeric(self) -> None:
        assert _parse_spoken_amount("starbucks") is None


class TestExtractAmount:
    @pytest.mark.parametrize(
        ("text", "default", "amount", "currency", "method"),
        [
            ("paid $40 for groceries", "USD", Decimal(40), "USD", ExtractionMethod.REGEX),
            ("$12.50 for coffee", "USD", Decimal("12.50"), "USD", ExtractionMethod.REGEX),
            # Thousands separators must not truncate the amount.
            ("spent 1,200 rupees on flights", "USD", Decimal(1200), "INR", ExtractionMethod.REGEX),
            (
                "bought coffee for 3 dollars and 50 cents",
                "USD",
                Decimal("3.50"),
                "USD",
                ExtractionMethod.REGEX,
            ),
            # Currency word ahead of the number.
            ("I paid Rs 250 for the taxi", "USD", Decimal(250), "INR", ExtractionMethod.REGEX),
            ("₹1200 for the electricity bill", "USD", Decimal(1200), "INR", ExtractionMethod.REGEX),
            # Spelled out, with and without a currency word.
            ("twenty five euros at the pharmacy", "USD", Decimal(25), "EUR", ExtractionMethod.WORDS),
            (
                "I spent twelve fifty at Starbucks",
                "USD",
                Decimal("12.50"),
                "USD",
                ExtractionMethod.WORDS,
            ),
            # Bare digits, anchored to a spend verb.
            ("spent 40 on groceries", "USD", Decimal(40), "USD", ExtractionMethod.REGEX),
        ],
    )
    def test_extracts(
        self,
        text: str,
        default: str,
        amount: Decimal,
        currency: str,
        method: ExtractionMethod,
    ) -> None:
        got_amount, got_currency, _span, got_method = extract_amount(text, default)
        assert got_amount == amount
        assert got_currency == currency
        assert got_method == method

    def test_unanchored_count_is_not_an_amount(self) -> None:
        """"2 coffees" is a quantity, not a price -- guessing here is worse
        than returning nothing and letting the LLM layer or the user decide."""
        amount, _currency, _span, method = extract_amount("2 coffees this morning", "USD")
        assert amount is None
        assert method is ExtractionMethod.NONE

    def test_defaults_to_user_currency_when_unmarked(self) -> None:
        _amount, currency, _span, _method = extract_amount("spent 40 on groceries", "INR")
        assert currency == "INR"


class TestExtractDate:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("lunch today", TODAY),
            ("coffee yesterday", date(2026, 8, 12)),
            ("dinner last night", date(2026, 8, 12)),
            ("groceries last friday", date(2026, 8, 7)),
            ("no date mentioned", TODAY),
        ],
    )
    def test_resolves_relative_dates(self, text: str, expected: date) -> None:
        when, _span = extract_date(text, TODAY)
        assert when == expected

    def test_returns_span_so_phrase_can_be_stripped(self) -> None:
        _when, span = extract_date("groceries yesterday", TODAY)
        assert span is not None


class TestExtractMerchant:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("coffee at Starbucks", "Starbucks"),
            ("groceries from Whole Foods", "Whole Foods"),
            ("lunch at home", None),  # a place, not a payee
            ("paid in cash", None),
        ],
    )
    def test_extracts_merchant(self, text: str, expected: str | None) -> None:
        merchant, _span = extract_merchant(text)
        assert merchant == expected


class TestCleanDescription:
    def test_strips_filler_and_punctuation(self) -> None:
        assert clean_description("I spent on groceries.", None) == "groceries"

    def test_strips_trailing_approximators(self) -> None:
        assert clean_description("grabbed lunch, about", None) == "grabbed lunch"

    def test_handles_overlapping_spans_right_to_left(self) -> None:
        """Spans are byte offsets into the original string, so they must be
        removed back-to-front or the later ones point at shifted text."""
        text = "spent 40 on groceries yesterday"
        assert clean_description(text, (6, 8), (22, 31)) == "groceries"


class TestExtractEndToEnd:
    def test_headline_case(self) -> None:
        result = extract("I spent twelve fifty at Starbucks", "USD", TODAY)
        assert result.amount == Decimal("12.50")
        assert result.currency == "USD"
        assert result.merchant == "Starbucks"
        assert result.date == TODAY
        assert result.method is ExtractionMethod.WORDS

    def test_date_phrase_does_not_leak_into_description(self) -> None:
        result = extract("spent 40 on groceries yesterday", "USD", TODAY)
        assert result.description == "groceries"
        assert result.date == date(2026, 8, 12)

    def test_description_never_empty(self) -> None:
        """Downstream the description is the categorizer's only input, so an
        empty string would silently produce garbage categories."""
        result = extract("$20", "USD", TODAY)
        assert result.description
