# YAFA

AI-powered expense tracker. Say what you spent; it transcribes, extracts the
amount and merchant, categorizes it semantically, and forecasts where your
spending is heading.

```
  voice ──► Whisper ──► extraction ──► BERT + Qdrant ──► Postgres ──► Power BI
            (CUDA)      regex / LLM     kNN vote                      Next.js
```

- **FastAPI** service, async throughout, with REST + WebSocket endpoints
- **Semantic categorization** via BERT sentence embeddings and Qdrant vector search
- **Voice capture** through `faster-whisper`, streamed live over a WebSocket
- **Forecasting** with exponential smoothing, prediction intervals, and per-category anomaly detection
- **Power BI** star schema and a checked-in, text-format semantic model
- **Next.js 16** front end

---

## How it works

**Voice → transaction.** `WS /ws/voice` (streaming) and `POST
/voice/transcribe` (one-shot) both return a *proposal* — nothing is saved
until `POST /voice/confirm`, since speech recognition mishears amounts and the
categorizer is only right ~3 times in 4. A correction made during review is
sent back with the model's original guess, so accuracy gets scored honestly.
Whisper does the transcription; the transcript is then parsed cheapest-first —
regex, then spoken numbers, then a Claude call only if those fail.

**Semantic categorization.** The description is embedded with
`all-MiniLM-L6-v2` and matched by cosine similarity against labeled exemplars
in Qdrant, top-10 neighbours voting. Below a similarity threshold it returns
no category rather than guess. Corrections feed straight back in as new
exemplars, so the model improves from real usage. Measured accuracy is
**90.7%** on hand-written phrases the training corpus never saw — see
[`docs/accuracy-notes.md`](docs/accuracy-notes.md).

**Forecasting.** Monthly simple exponential smoothing, 80% prediction
intervals, per-category anomaly detection. Chosen by backtesting eight
candidates against real series — the previous ARIMA(5,1,0) placed last of
eight. Under 6 months of history it shows no forecast rather than a
meaningless one, and a run of 6+ empty months is treated as a fresh start
rather than dragging a stale average forward. Details:
[`docs/forecasting-notes.md`](docs/forecasting-notes.md).

**The interface.** Deep green and cream, one `@theme` block driving every
color, no dark mode. `/` is a static, zero-JS landing page; the app starts at
`/login`.

---

## Layout

```
apps/
  api/            FastAPI service
    app/
      core/       config, database, security, deps, logging
      models/     SQLAlchemy ORM
      routers/    auth, transactions, voice, categorize, forecast, powerbi, ws
      services/   categorizer, speech, nlp_extract, llm_extract, pipeline,
                  forecasting, demo_seed
    alembic/      migrations
    tests/        102 tests
  web/            Next.js 16 + Tailwind v4 + TanStack Query + Recharts
                  routes: / (landing) · /login · /record · /transactions · /insights
tools/            corpus building, Qdrant seeding, evaluation, SQLite migration
powerbi/          star-schema SQL + PBIP semantic model (TMDL)
infra/            Dockerfiles
compose.yaml      postgres · qdrant · api · web
```

## Commands

```sh
uv run pytest apps/api/tests            # 102 tests; integration ones skip if the stack is down
uv run ruff check apps/api tools
uv run mypy apps/api/app

uv run python -m tools.seed_qdrant            # index the corpus (--recreate to rebuild)
uv run python -m tools.eval_categorizer       # held-out + probe accuracy, confusion matrix
uv run python -m tools.eval_forecasting       # forecast MAE vs naive baselines
uv run python -m tools.build_training_data    # regenerate the corpus from us_expense_spec
uv run python -m tools.build_demo_data        # regenerate the demo account's transactions
uv run alembic revision --autogenerate -m "..."

cd apps/web && npm run build
```

Importing the old SQLite data:

```sh
git show 11c4de1:database.db > /tmp/database.db     # pre-revamp, from git history
uv run python -m tools.migrate_sqlite_to_postgres \
  --yafa-db backend/yafa.db --legacy-db /tmp/database.db
```

Both sources are idempotent and deduplicate on
`(user, date, description, amount)`. Historical rows land in a `demo_legacy`
account — the `demo` account is wiped and reseeded on every demo login, so
importing into it would destroy the data on the first click.

## Power BI

Apply `powerbi/sql/star_schema.sql`, open `powerbi/YAFA.pbip`, point it at
your database, refresh. Six tables, 20 DAX measures. Report pages ship empty
on purpose — Power BI's visual-container JSON is undocumented and
version-sensitive, so [`powerbi/README.md`](powerbi/README.md) gives exact
field placements instead of a fragile checked-in layout.

## Notes on the rewrite

The 2024 hackathon build already had the right instinct — a FastAPI backend
behind a thin client, BERT + Qdrant for categorization — but the shape around
it didn't hold up. A Streamlit multi-page app called that backend over plain
`requests`, backed by one SQLite file committed to the repo and recreated with
`Base.metadata.create_all()` on every boot; there was no migration history, no
async, and voice capture was a single blocking HTTP round trip. Auth was two
systems wired together — a YAML credential store driving Streamlit's session
cookie, separate from the backend's own JWT issuing.

The rewrite keeps the same core idea and changes the shape it runs in: two
independently deployable apps (`apps/api`, `apps/web`) talking over a typed
REST + WebSocket boundary, Postgres with Alembic migrations instead of a
committed database file, and Qdrant running as a real service rather than an
embedded client that held an exclusive lock on the collection. Inside the API,
a `pipeline` service now sits between routers and the model layer so the
WebSocket and HTTP voice entry points share one code path instead of each
reimplementing extraction and categorization. Auth collapsed to one JWT-based
story. Offline tooling — corpus generation, evaluation, seeding — moved out of
the backend into its own top-level package (`tools/`) so it stops shipping in
the API's runtime image. None of this existed before: a CI pipeline, a test
suite, and a Power BI reporting layer alongside the app itself.

One deliberate scope cut: the investment page wasn't ported. It rendered
returns from `random.uniform()`, and a rewrite is the wrong time to carry
a fabricated feature forward unexamined.

---

## Quick start

Requires Docker and [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(64))"   # paste into YAFA_JWT_SECRET

docker compose up -d postgres qdrant
uv sync --group ml
uv run alembic upgrade head
uv run python -m tools.seed_qdrant                # index the categorization corpus
uv run uvicorn app.main:app --reload --app-dir apps/api

cd apps/web && npm install && npm run dev
```

Open http://localhost:3000 and follow **Try the demo** through to the sign-in
page — the button there seeds 18 months of data and drops you into the app, no
signup. API docs are at http://localhost:8000/docs.

Everything in one shot instead:

```sh
docker compose up --build
```

> **Port note.** Postgres publishes on **55432**, not 5432. Local PostgreSQL
> installs commonly hold both 5432 and 5433 (one per major version); the host
> connection silently reaches those instead, which surfaces as
> "password authentication failed" rather than a port conflict.
