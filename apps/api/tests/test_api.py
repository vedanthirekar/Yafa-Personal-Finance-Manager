"""End-to-end route tests against a real Postgres.

Marked `integration` and skipped when the compose stack isn't up, so a cold
`pytest` still passes on a fresh checkout.
"""

import pytest
from httpx import AsyncClient

from .conftest import requires_stack

pytestmark = [pytest.mark.integration, requires_stack]


class TestHealth:
    async def test_health_is_liveness_only(self, client: AsyncClient) -> None:
        """Must not touch Postgres or Qdrant: the container healthcheck polls
        this, and failing on a dependency blip would restart a healthy
        process."""
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_readiness_reports_dependencies(self, client: AsyncClient) -> None:
        response = await client.get("/health/ready")
        body = response.json()
        assert "database" in body["checks"]
        assert "qdrant" in body["checks"]


class TestAuth:
    async def test_register_then_use_token(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get("/auth/me")
        assert response.status_code == 200
        assert response.json()["name"] == "Test User"

    async def test_duplicate_registration_is_rejected(self, client: AsyncClient) -> None:
        import uuid

        payload = {
            "username": f"dup_{uuid.uuid4().hex[:10]}",
            "email": f"dup_{uuid.uuid4().hex[:10]}@example.com",
            "name": "Dup",
            "password": "correct-horse-battery-staple",
        }
        assert (await client.post("/auth/register", json=payload)).status_code == 201

        conflict = await client.post("/auth/register", json=payload)
        assert conflict.status_code == 409
        # One generic message for both collisions -- naming the matched field
        # would turn this into a username/email enumeration oracle.
        assert "username or email" in conflict.json()["detail"]

    async def test_wrong_password_rejected(self, client: AsyncClient) -> None:
        import uuid

        username = f"pw_{uuid.uuid4().hex[:10]}"
        await client.post(
            "/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "name": "PW",
                "password": "correct-horse-battery-staple",
            },
        )
        response = await client.post(
            "/auth/login", json={"username": username, "password": "wrong"}
        )
        assert response.status_code == 401

    async def test_protected_route_requires_token(self, client: AsyncClient) -> None:
        client.headers.pop("Authorization", None)
        assert (await client.get("/auth/me")).status_code == 401

    async def test_refresh_returns_new_pair(self, client: AsyncClient) -> None:
        import uuid

        username = f"rf_{uuid.uuid4().hex[:10]}"
        registered = await client.post(
            "/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "name": "RF",
                "password": "correct-horse-battery-staple",
            },
        )
        refresh_token = registered.json()["refresh_token"]

        response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert response.status_code == 200
        assert response.json()["access_token"]

    async def test_access_token_rejected_at_refresh(self, client: AsyncClient) -> None:
        """An access token must not be redeemable for a fresh pair."""
        import uuid

        username = f"ax_{uuid.uuid4().hex[:10]}"
        registered = await client.post(
            "/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "name": "AX",
                "password": "correct-horse-battery-staple",
            },
        )
        access = registered.json()["access_token"]

        response = await client.post("/auth/refresh", json={"refresh_token": access})
        assert response.status_code == 401


class TestTransactions:
    async def test_create_and_list(self, auth_client: AsyncClient) -> None:
        created = await auth_client.post(
            "/transactions",
            json={
                "date": "2026-08-13",
                "description": "flat white",
                "category": "Food",
                "amount": "4.75",
                "merchant": "Blue Bottle",
            },
        )
        assert created.status_code == 201
        assert created.json()["merchant"] == "Blue Bottle"

        listed = await auth_client.get("/transactions")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

    async def test_amount_precision_survives_roundtrip(self, auth_client: AsyncClient) -> None:
        """The reason amount is NUMERIC and serialized as a string: 0.1 + 0.2
        style drift must not appear anywhere in the path."""
        created = await auth_client.post(
            "/transactions",
            json={
                "date": "2026-08-13",
                "description": "precision",
                "category": "Food",
                "amount": "1234567.89",
            },
        )
        assert created.json()["amount"] == "1234567.89"

    async def test_rejects_negative_amount(self, auth_client: AsyncClient) -> None:
        response = await auth_client.post(
            "/transactions",
            json={
                "date": "2026-08-13",
                "description": "bad",
                "category": "Food",
                "amount": "-5.00",
            },
        )
        assert response.status_code == 422

    async def test_pagination(self, auth_client: AsyncClient) -> None:
        for i in range(5):
            await auth_client.post(
                "/transactions",
                json={
                    "date": "2026-08-13",
                    "description": f"item {i}",
                    "category": "Food",
                    "amount": "1.00",
                },
            )
        page = await auth_client.get("/transactions?limit=2&offset=0")
        body = page.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5

    async def test_cannot_read_another_users_transaction(
        self, client: AsyncClient, auth_client: AsyncClient
    ) -> None:
        """Ownership is part of the lookup, so a foreign id is a 404 -- not a
        403, which would confirm the row exists."""
        import uuid

        created = await auth_client.post(
            "/transactions",
            json={
                "date": "2026-08-13",
                "description": "private",
                "category": "Food",
                "amount": "9.99",
            },
        )
        victim_id = created.json()["id"]

        username = f"other_{uuid.uuid4().hex[:10]}"
        attacker = await client.post(
            "/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "name": "Other",
                "password": "correct-horse-battery-staple",
            },
        )
        auth_client.headers["Authorization"] = f"Bearer {attacker.json()['access_token']}"

        assert (await auth_client.get(f"/transactions/{victim_id}")).status_code == 404
        assert (await auth_client.delete(f"/transactions/{victim_id}")).status_code == 404

    async def test_delete(self, auth_client: AsyncClient) -> None:
        created = await auth_client.post(
            "/transactions",
            json={
                "date": "2026-08-13",
                "description": "temp",
                "category": "Food",
                "amount": "1.00",
            },
        )
        txn_id = created.json()["id"]
        assert (await auth_client.delete(f"/transactions/{txn_id}")).status_code == 204
        assert (await auth_client.get(f"/transactions/{txn_id}")).status_code == 404

    async def test_category_breakdown_percentages(self, auth_client: AsyncClient) -> None:
        for category, amount in [("Food", "75.00"), ("Health", "25.00")]:
            await auth_client.post(
                "/transactions",
                json={
                    "date": "2026-08-13",
                    "description": category,
                    "category": category,
                    "amount": amount,
                },
            )
        rows = (await auth_client.get("/transactions/stats/by-category")).json()
        by_category = {r["category"]: r for r in rows}
        assert by_category["Food"]["pct_of_total"] == pytest.approx(75.0)
        assert by_category["Health"]["pct_of_total"] == pytest.approx(25.0)


class TestPowerBI:
    async def test_feeds_return_expected_shape(self, auth_client: AsyncClient) -> None:
        await auth_client.post(
            "/transactions",
            json={
                "date": "2026-08-13",
                "description": "pbi",
                "category": "Food",
                "amount": "10.00",
                "merchant": "Test Shop",
            },
        )

        transactions = (await auth_client.get("/powerbi/fct_transactions")).json()
        assert transactions
        # Star-schema key naming is what the semantic model binds to.
        assert {"transaction_key", "date_key", "category_key", "merchant_key"} <= set(
            transactions[0]
        )

        for endpoint in ["dim_category", "dim_merchant", "dim_date", "fct_forecast"]:
            assert (await auth_client.get(f"/powerbi/{endpoint}")).status_code == 200

    async def test_csv_variant(self, auth_client: AsyncClient) -> None:
        await auth_client.post(
            "/transactions",
            json={
                "date": "2026-08-13",
                "description": "csv",
                "category": "Food",
                "amount": "3.00",
            },
        )
        response = await auth_client.get("/powerbi/fct_transactions?format=csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "transaction_key" in response.text


class TestForecastRoute:
    async def test_empty_account_does_not_error(self, auth_client: AsyncClient) -> None:
        """A brand-new user has no history. That is a normal state, not a 500."""
        response = await auth_client.get("/forecast/me")
        assert response.status_code == 200
        body = response.json()
        assert body["overall"]["is_fitted"] is False
        assert body["overall"]["forecast"] == []


class TestVoiceConfirm:
    """``POST /voice/confirm`` is the only write path for voice.

    Transcription and the WebSocket return proposals; the user approves them
    here. That makes this the point where the model's guess and the user's
    decision must be recorded as two separate things.
    """

    @staticmethod
    def _proposal(**overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "transcript": "twelve fifty at Starbucks",
            "description": "coffee",
            "amount": "12.50",
            "currency": "USD",
            "merchant": None,
            "date": "2026-01-15",
            "category": "Food",
            "confidence": 0.91,
            "extraction_method": "words",
            "predicted_category": "Food",
            "predicted_confidence": 0.91,
        }
        payload.update(overrides)
        return payload

    async def test_amount_is_required(self, auth_client: AsyncClient) -> None:
        response = await auth_client.post("/voice/confirm", json=self._proposal(amount=None))
        assert response.status_code == 422

    async def test_keeping_the_suggestion_counts_as_accepted(
        self, auth_client: AsyncClient
    ) -> None:
        response = await auth_client.post("/voice/confirm", json=self._proposal())
        assert response.status_code == 201
        assert response.json()["category"] == "Food"

        quality = (await auth_client.get("/transactions/stats/categorization-quality")).json()
        assert quality["predictions"] == 1
        assert quality["accepted"] == 1

    async def test_correcting_before_saving_is_recorded_as_a_rejection(
        self, auth_client: AsyncClient
    ) -> None:
        """The regression this guards against is subtle and silent.

        The client posts back the object it was given, so ``category`` holds
        the user's correction by the time it arrives. Storing that as the
        prediction would mean the categorizer scored itself on the user's own
        answer -- 100% accuracy, forever, no matter how wrong it was.
        """
        response = await auth_client.post(
            "/voice/confirm",
            json=self._proposal(category="Entertainment", predicted_category="Food"),
        )
        assert response.status_code == 201
        # The user's choice is what gets saved...
        assert response.json()["category"] == "Entertainment"

        # ...and the model is scored against what it actually said.
        quality = (await auth_client.get("/transactions/stats/categorization-quality")).json()
        assert quality["predictions"] == 1
        assert quality["accepted"] == 0
        assert quality["acceptance_rate"] == 0.0

    async def test_model_declining_to_guess_is_not_an_acceptance(
        self, auth_client: AsyncClient
    ) -> None:
        """Below the similarity threshold the categorizer returns nothing.

        That is a miss, not a hit. Folding it in with correct answers would
        let the acceptance rate rise every time the model gave up.
        """
        response = await auth_client.post(
            "/voice/confirm",
            json=self._proposal(category=None, predicted_category=None, confidence=0.0),
        )
        assert response.status_code == 201
        assert response.json()["category"] == "Uncategorized"

        quality = (await auth_client.get("/transactions/stats/categorization-quality")).json()
        assert quality["accepted"] == 0
