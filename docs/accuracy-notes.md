# Categorizer accuracy — where it stands

Regenerate with `uv run python -m tools.eval_categorizer`, which writes
`data/eval_report.json`.

## Two numbers, and only one of them means anything

| | accuracy | what it measures |
|---|---|---|
| Held-out split | **0.995** | 80/20 stratified split of the generated corpus. Both sides come from the same generator, so this is internal consistency. Read it as a floor. |
| **Hand-written probes** | **0.907** | `data/eval_probes.csv` — 129 phrases written by hand with merchants and wordings the corpus has never seen. **This is the real number.** |

Model: `all-MiniLM-L6-v2`, frozen, k=10 similarity-weighted vote.

The gap between the two is the useful diagnostic. When it widens, the corpus is
drifting away from the way people actually talk.

### Comparing against the old number honestly

The previous corpus reported **0.759**, and that figure is comparable to the
**0.995** above, not to the 0.907 — both are in-distribution splits. The old
setup had no out-of-distribution measurement at all, which was the core problem
with it: the test split was drawn from the same four templates as the training
split, so the number flattered itself.

The honest claim is: *90.7% on held-out phrasings the corpus has never seen.*

## What was wrong before

The old corpus was `data/categories.csv` (bare keywords through four fixed
templates) plus `data/sample-data.csv` (an anonymised Indian expense ledger).

1. **Exemplars didn't look like queries.** `pipeline.process_transcript`
   categorizes on `"{description} {merchant}"` — "coffee starbucks" — but only
   **1.3%** of exemplars (36 of 2,739) contained a brand name. The one signal
   the pipeline deliberately adds was the one the corpus couldn't match on.
2. **Two categories were unreachable.** `Apparel` and `Entertainment` are in the
   app's category list, but the builder folded them into Household and Social
   Life. No exemplar could ever vote for them. Separately, the corpus could
   predict `Investment` and `Money transfer`, which the UI has no option for —
   8% of rows carried a label the user couldn't select.
3. **The tail was starved and narrow.** Subscription had 60 exemplars against
   Social Life's 701, and all 60 were video streaming services — so "gym
   membership" or "iCloud storage" matched nothing. Recall was 0.50.
4. **127 keywords appeared under more than one category** (`art`, `music`,
   `festivals`, `cuisine`…). Same string, two labels, unanswerable by
   construction.
5. **Transportation was 70% anonymisation placeholders** — "2 Current Residence
   to Place 0". Its 0.89 F1 was partly the model learning `to Place` →
   Transportation, an artifact that doesn't survive contact with real speech.

## What replaced it

`tools/us_expense_spec.py` — a curated US vocabulary of merchants and the items
they actually sell, grouped by affinity so the generator never emits "museum
admission steam". `tools/build_training_data.py` expands it into ~7,800 exemplars,
balanced at 800 per category (Education lands at 620, its vocabulary is
smaller), weighted toward the `"{item} {merchant}"` shape the pipeline queries
with.

The same spec generates `data/demo-transactions.csv` via
`tools/build_demo_data.py`, so the demo account shows merchants the model was
trained to recognise, with USD amounts that make sense.

`data/categories.csv` and `data/sample-data.csv` are now unread. Left on disk
rather than deleted.

## Weakest classes now

| Category | F1 (probes) | note |
|---|---|---|
| Tourism | 0.78 | Confused with Transportation — "airport parking", "shuttle to the hotel" genuinely sit on the boundary. |
| Household | 0.87 | Utility bills vs Subscription recurring charges. |
| Transportation | 0.89 | The other side of the Tourism confusion. |

Tourism/Transportation is the one pair worth looking at next, and the fix is
probably taxonomy rather than data: decide once whether travel-day ground
transport is Transportation or Tourism, and write it into the spec's judgment
calls.

## Still true, still worth having

- Every prediction is persisted to `category_predictions` with its confidence
  and model version; corrections flip `accepted` and set `corrected_to`. That's
  a **live accuracy signal from real user behaviour** — how often people keep
  the suggestion — which beats any offline number. Query it via
  `GET /transactions/stats/categorization-quality`.
- Corrections index back into Qdrant tagged `user_correction`, kept
  distinguishable from seed rows so evaluation stays comparable.
