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
uv run python -m ml.seed_qdrant                # index the categorization corpus
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

`WS /ws/voice` takes webm/opus chunks from the browser's `MediaRecorder`,
returns interim transcripts, and on `finalize` returns one authoritative
result. `POST /voice/transcribe` does the same without streaming.

**Neither one saves anything.** Both return a proposal that the user reviews
and commits with `POST /voice/confirm`, the single write path for voice.
Speech recognition mishears amounts and the categorizer is right about three
times in four, so writing straight from a recording fills the ledger with rows
nobody agreed to. When the user fixes a category during that review, the
original prediction is sent back alongside it — otherwise the model would be
scored against the user's own answer and read as perfect forever.

Whisper (`small.en`) auto-selects CUDA with `int8_float16` and falls back to
CPU — including when a CUDA load fails at runtime, not just when no GPU is
present.

The transcript is then parsed in layers, cheapest first:

| Layer | Handles | Cost |
|---|---|---|
| Regex + currency map | `$12.50`, `1,200 rupees`, `Rs 250`, `₹1200` | free |
| Spoken numbers | "twenty five dollars", "twelve fifty" | free |
| Claude structured output | everything messier | one API call |

Two details worth knowing. Spoken **"twelve fifty" means 12.50**, but
`word2number` sums it to 62 — so two-token shapes are disambiguated explicitly
(`<unit|teen> <tens>` is a price, `<tens> <unit>` is additive). And currency is
resolved per user; the previous build parsed USD only while rendering "Rs.".

The LLM layer is entirely optional. With no `ANTHROPIC_API_KEY`, the pipeline
runs fully local and simply loses the messy-transcript fallback.

### Semantic categorization

The description is embedded with `all-MiniLM-L6-v2` (a distilled 6-layer BERT,
384-dim) and matched by cosine similarity against labeled exemplars in Qdrant.
The top-10 neighbours vote, weighted by similarity; confidence is the winner's
share of total similarity mass, so it reflects how *decisive* the vote was
rather than how close one match landed.

Below a similarity threshold the API returns no category at all. Saying "I'm
not sure, pick one" beats confidently guessing from a distant match.

**Corrections are training data.** Changing a category marks the prediction
rejected, pins the merchant's default so it skips the model next time, and
indexes a new exemplar into Qdrant tagged `user_correction` — kept
distinguishable from the seed corpus so evaluation stays comparable.

> **Accuracy is 90.7%, measured the hard way.** The eval reports two numbers:
> 99.5% on a held-out split of the generated corpus, and **90.7% on 129
> hand-written phrases using merchants and wordings the corpus has never seen**
> (`data/eval_probes.csv`). The second is the one quoted here — the first only
> proves the generator is self-consistent. Run
> `uv run python -m ml.eval_categorizer` for both, plus per-class F1 and a
> confusion matrix. Full write-up in `docs/accuracy-notes.md`.

### Forecasting

Monthly **simple exponential smoothing** with 80% prediction intervals,
per-category series, and z-score anomaly detection scoped per category — a $400
rent month is normal, a $400 coffee month is not.

**The model was chosen by measurement, not by reputation.**
`uv run python -m ml.eval_forecasting` backtests eight candidates against the
real series — expanding window, one-step-ahead, scored against a naive "next
month looks like last month" baseline. The previous ARIMA(5,1,0) placed **last
of eight**, 45% worse than doing nothing, because it estimates five
autoregressive coefficients from seventeen differenced points. Numbers and
reasoning: [`docs/forecasting-notes.md`](docs/forecasting-notes.md).

Exponential smoothing is a weighted average of past months where recent months
count more, and how much more is one parameter (α) fitted per account. That
single parameter spans both methods that beat ARIMA in the backtest — α→1 is
"last month repeats", α→0 is "the long-run average" — so the model adapts to
each user with no per-user model selection or hardcoded window. It is also
exactly ARIMA(0,1,1): same family as before, correct number of parameters.

Three things the series does that a bare `.fit()` wouldn't:

| | Why |
|---|---|
| **Under 6 months → no forecast at all** | `months_of_history` and `months_required` come back instead, and the UI counts down. Below that α is fitted to three or four points and the interval built from it means nothing. The old build showed a flat mean here and called it a projection. |
| **The current month is excluded from the fit** | The newest bucket is only as complete as today's date. Smoothing weights the latest observation most heavily, so a half-finished month reads as a collapse in spending — and it's the point the model trusts most. It stays in `history` for the chart. |
| **Six-plus empty months = dormancy, and everything before it is dropped** | Gaps are zero-filled so non-adjacent months aren't treated as consecutive — right for a quiet month, wrong for a year off. The imported historical account has an 18-month hole; including it widened the 80% band to 8.4× the forecast. Trimming to the current era brought that to 1.9×. |

Intervals come from the closed-form ETS(A,N,N) variance, `σ²[1 + (h−1)α²]`
(Hyndman & Athanasopoulos §7.7). They are still wide — roughly 1.5× the
forecast on the demo account — because monthly spending genuinely varies that
much. No model shrinks that; the honest move is to show it.

### The interface

Deep green and cream, pill buttons, and a serif for anything that states a
number. The whole palette lives in the `@theme` block in
`apps/web/src/app/globals.css`, which is what makes `bg-forest-900` and
`text-ink-subtle` real utility classes — no component hardcodes a hex value,
and retheming is one file.

There is no dark mode, deliberately: one committed look, with
`color-scheme: light` declared so native date pickers, selects, and scrollbars
don't render in dark chrome when the OS is set to dark.

`/` is a static marketing page — a plain server component with no hooks and no
data fetching, so Next ships zero JavaScript for it. The app itself starts at
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
ml/               corpus building, Qdrant seeding, evaluation, SQLite migration
powerbi/          star-schema SQL + PBIP semantic model (TMDL)
infra/            Dockerfiles
compose.yaml      postgres · qdrant · api · web
```

## Commands

```sh
uv run pytest apps/api/tests            # 102 tests; integration ones skip if the stack is down
uv run ruff check apps/api ml
uv run mypy apps/api/app

uv run python -m ml.seed_qdrant            # index the corpus (--recreate to rebuild)
uv run python -m ml.eval_categorizer       # held-out + probe accuracy, confusion matrix
uv run python -m ml.eval_forecasting       # forecast MAE vs naive baselines
uv run python -m ml.build_training_data    # regenerate the corpus from us_expense_spec
uv run python -m ml.build_demo_data        # regenerate the demo account's transactions
uv run alembic revision --autogenerate -m "..."

cd apps/web && npm run build
```

Importing the old SQLite data:

```sh
git show 11c4de1:database.db > /tmp/database.db     # pre-revamp, from git history
uv run python -m ml.migrate_sqlite_to_postgres \
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
