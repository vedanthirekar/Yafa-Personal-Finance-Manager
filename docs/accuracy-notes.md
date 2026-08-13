# Categorizer accuracy — diagnosis and plan

**Not worked on in this pass.** Written down so the analysis isn't re-derived
later.

## Where it stands

`data/eval_report.json`, regenerated with `uv run python -m ml.eval_categorizer`:

| | |
|---|---|
| Accuracy | **0.759** |
| Split | stratified 80/20, 2191 train / 548 test |
| Model | `all-MiniLM-L6-v2`, frozen, k=10 similarity-weighted vote |

Worst classes:

| Category | F1 | Recall |
|---|---|---|
| Tourism | 0.50 | 0.43 |
| Subscription | 0.60 | 0.50 |
| Health | 0.66 | — |

## Why — it's the corpus, not the model

Measured over `data/categories.csv` (1816 rows, 1651 unique keywords):

**1. 127 keywords appear under more than one category.** `art`, `music`,
`dance`, `theater`, `film`, `opera`, `ballet`, `folklore`, `festivals`,
`celebration`, `cuisine`, `cooking`, `performance`, `tradition`… Culture,
Tourism, Entertainment and Festivals are mutually contaminated. No model can
beat label noise: the same string carries two different labels in training, so
some test items are unanswerable by construction.

**2. The tail is starved.** Most categories have 100 keywords. `subscription`
has **30**; `gift` has **15**. Under a kNN vote, a class with a third of the
exemplar density loses ties it should win — which is exactly the recall
collapse (0.50) that Subscription shows.

**3. The corpus is template-generated.** Keywords are expanded through four
fixed templates: `"spent money on {kw}"`, `"paid for {kw}"`, `"{kw} expense"`,
`"bought {kw}"`. The model partly learns template shape rather than semantics,
and — worse — the *test* split is drawn from the same templates, so the
reported number is measured on unrealistically self-similar text.

These three facts map directly onto the two failing classes. Reproduce with:

```sh
uv run python -c "
import pandas as pd, collections
df = pd.read_csv('data/categories.csv')
c = collections.Counter(df['words'].astype(str).str.strip().str.lower())
print('keywords in >1 category:', sum(1 for n in c.values() if n > 1))
print(df['category'].value_counts().tail(5))
"
```

## Plan, in order

Data first. Model changes before the corpus is fixed will fit noise.

1. **De-collide the taxonomy.** Resolve all 127 duplicates — assign each
   keyword one owner category or drop it. Emit `ml/taxonomy_conflicts.csv` as
   an audit trail.
2. **Balance the tail.** Bring `subscription` and `gift` to parity with a
   curated keyword and real-merchant list (Netflix, Spotify, Prime, iCloud…).
3. **Replace templates with realistic text.** Mine the 2176 real descriptions
   in `data/sample-data.csv` and add a curated merchant list. Target ≥8k
   examples that look like things people actually say and banks actually print.
4. **Then** consider fine-tuning the encoder — `SentenceTransformerTrainer`
   with `MultipleNegativesRankingLoss` on labeled pairs. Baselines to report
   alongside it: frozen MiniLM kNN (today's 0.759), frozen `bge-base-en-v1.5`
   kNN, and a logistic-regression head on frozen embeddings.
5. **Evaluate honestly.** Stratified 5-fold *plus* a held-out set drawn only
   from real `sample-data.csv` descriptions, never from generated templates —
   a template-only test set flatters the model.
6. **Only then**, if the confusion matrix shows two classes a human couldn't
   separate either, merge them — with the matrix as the evidence.

## Two things already in place

- `ml/eval_categorizer.py` writes a **confusion matrix** alongside per-class
  F1. The interesting failures are confusions between specific pairs, which
  per-class scores alone don't show.
- Every prediction is persisted to `category_predictions` (predicted category,
  confidence, model version) and corrections flip `accepted` and set
  `corrected_to`. That gives a **live accuracy signal from real user
  behaviour** — how often people keep the suggestion — which is arguably more
  honest than any offline number against a synthetic corpus. Query it via
  `GET /transactions/stats/categorization-quality` or the
  `vw_powerbi_categorization_quality` view.

## Until then

The resume bullet should carry the measured number, not 92%.
