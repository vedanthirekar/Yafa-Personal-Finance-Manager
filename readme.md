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

---

## How it works

### Voice → transaction

`WS /ws/voice` streams interim transcripts from the browser's `MediaRecorder`
and returns one final result; `POST /voice/transcribe` does the same
non-streaming. **Neither saves anything** — both return a proposal, and
`POST /voice/confirm` is the only write path. Speech recognition mishears
amounts and the categorizer is right ~3 times in 4, so writing straight from a
recording would fill the ledger with rows nobody agreed to. A user correction
during review is sent back alongside the model's original guess, so the model
can be scored honestly instead of always looking right.

Whisper (`small.en`) auto-selects CUDA and falls back to CPU. The transcript
is parsed cheapest-first: regex + currency map, then spoken numbers ("twelve
fifty"), then — only if those fail — a Claude call for anything messier.
Optional: with no `ANTHROPIC_API_KEY` the pipeline runs fully local and loses
just that last fallback.

### Semantic categorization

The description is embedded with `all-MiniLM-L6-v2` and matched by cosine
similarity against labeled exemplars in Qdrant; the top-10 neighbours vote,
weighted by similarity. Below a similarity threshold the API returns no
category at all rather than guess from a distant match. Every correction
pins the merchant's default and is indexed back into Qdrant as a new
exemplar, so the model improves from real usage.

> **Accuracy is 90.7%**, measured on 129 hand-written phrases the training
> corpus never saw (`data/eval_probes.csv`) — not the 99.5% held-out split,
> which only shows the generator is self-consistent. Run
> `uv run python -m tools.eval_categorizer` for both plus a confusion matrix.
> Write-up: [`docs/accuracy-notes.md`](docs/accuracy-notes.md).

### Forecasting

Monthly **simple exponential smoothing**, 80% prediction intervals, and
per-category z-score anomaly detection — a $400 rent month is normal, a $400
coffee month is not. Chosen by backtesting eight candidates against real
series (`uv run python -m tools.eval_forecasting`); the previous ARIMA(5,1,0)
placed last of eight, 45% worse than a naive "repeat last month" baseline.
Details: [`docs/forecasting-notes.md`](docs/forecasting-notes.md).

Three guardrails a bare `.fit()` wouldn't have: under 6 months of history
returns no forecast at all rather than a meaningless one; the current
(incomplete) month is excluded from fitting but still shown on the chart; and
6+ empty months are treated as dormancy, with history before the gap dropped
so a year-old account doesn't look like one long streak. Prediction intervals
stay wide (~1.5× the forecast) because monthly spending genuinely varies that
much — the honest move is to show it, not shrink it.

### The interface

Deep green and cream, pill buttons, a serif for numbers — the whole palette is
one `@theme` block in `apps/web/src/app/globals.css`, so no component
hardcodes a hex value. No dark mode, deliberately, with `color-scheme: light`
set so native pickers don't switch chrome on their own. `/` is a static,
zero-JS marketing page; the app itself starts at `/login`.

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
uv run ruff check apps/api ml
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

## Configuration

Everything is `YAFA_`-prefixed; see `.env.example`.

| Variable | Default | Notes |
|---|---|---|
| `YAFA_JWT_SECRET` | *(none)* | Required, ≥32 chars. The API refuses to boot without it. |
| `YAFA_DATABASE_URL` | `…@localhost:55432/yafa` | |
| `YAFA_QDRANT_URL` | `http://localhost:6333` | |
| `YAFA_WHISPER_MODEL_SIZE` | `small.en` | `base.en` is faster, less accurate |
| `YAFA_WHISPER_DEVICE` | `auto` | `auto` \| `cuda` \| `cpu` |
| `ANTHROPIC_API_KEY` | *(none)* | Optional; enables the LLM extraction fallback |

GPU inference locally: `uv sync --extra gpu` installs CUDA torch from
PyTorch's index. The Docker image intentionally stays on CPU wheels.

## Power BI

See [`powerbi/README.md`](powerbi/README.md). Short version: apply
`powerbi/sql/star_schema.sql`, open `powerbi/YAFA.pbip`, point the
`ServerParam` / `DatabaseParam` parameters at your database, refresh.

Six tables, seven single-direction relationships, 20 DAX measures. The report
pages ship empty on purpose — Power BI's visual-container JSON is undocumented
and version-sensitive, so the README gives exact field placements instead.

## Notes on the rewrite

This replaces a 2024 hackathon build (Streamlit + a flat SQLite table rewritten
in full on every insert). Things that changed and why:

- `amount` is `NUMERIC`, not `FLOAT`. Binary floats can't represent most
  decimal fractions, so sums drifted.
- NLTK is gone. Its last job was finding a bare integer — a regex does that
  better, and importing it ran `nltk.download()` on every process start.
- Qdrant runs as a service. Embedded mode took an exclusive directory lock, so
  reseeding meant stopping the API.
- argon2 replaces bcrypt, with transparent verification of legacy hashes and
  rehash-on-login. bcrypt stays a runtime dependency for exactly that reason.
- `jwt_secret` has no default. Signing tokens with a well-known key is worse
  than refusing to start.
- The investment page was deleted rather than ported: it generated its returns
  with `random.uniform()`.
