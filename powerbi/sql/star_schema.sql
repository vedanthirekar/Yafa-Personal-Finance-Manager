-- Star-schema views for Power BI DirectQuery.
--
-- Apply once against the app database:
--   docker compose exec -T postgres psql -U yafa -d yafa < powerbi/sql/star_schema.sql
--
-- Power BI connects to these rather than the base tables, for three reasons:
--   * the column names are the ones the semantic model expects, so renaming a
--     base column doesn't silently break the report;
--   * the grain is explicit (one row per transaction / category / merchant /
--     day), which is what Power BI's relationship engine needs;
--   * the joins live in SQL rather than in Power Query, so refreshes push work
--     to Postgres instead of pulling every row into memory.
--
-- Every view carries user_id. Power BI filters on it via a parameter -- these
-- views are NOT a security boundary, they're a reporting shape. Anyone with
-- database credentials can read every user's rows, exactly as they could from
-- the base tables.

-- ---------------------------------------------------------------------------
-- dim_date -- contiguous calendar spanning the data
-- ---------------------------------------------------------------------------
-- Power BI's time intelligence (MoM, YTD, running totals) requires a gap-free
-- date table marked as the model's date dimension. Deriving it from
-- generate_series rather than from transaction dates guarantees no holes, even
-- in months where nothing was spent.
CREATE OR REPLACE VIEW vw_powerbi_dim_date AS
WITH bounds AS (
    SELECT
        COALESCE(MIN(date), CURRENT_DATE) AS min_date,
        COALESCE(MAX(date), CURRENT_DATE) AS max_date
    FROM transactions
)
SELECT
    d::date                                        AS date_key,
    EXTRACT(YEAR    FROM d)::int                   AS year,
    EXTRACT(QUARTER FROM d)::int                   AS quarter_number,
    'Q' || EXTRACT(QUARTER FROM d)::text           AS quarter,
    EXTRACT(MONTH   FROM d)::int                   AS month_number,
    TO_CHAR(d, 'FMMonth')                          AS month_name,
    TO_CHAR(d, 'YYYY-MM')                          AS year_month,
    DATE_TRUNC('month', d)::date                   AS month_start,
    EXTRACT(DAY FROM d)::int                       AS day_of_month,
    TO_CHAR(d, 'FMDay')                            AS day_name,
    EXTRACT(ISODOW FROM d)::int                    AS day_of_week_number,
    (EXTRACT(ISODOW FROM d) >= 6)                  AS is_weekend
FROM bounds, generate_series(bounds.min_date, bounds.max_date, INTERVAL '1 day') AS d;


-- ---------------------------------------------------------------------------
-- dim_category
-- ---------------------------------------------------------------------------
-- Grain: one row per (user, category). Budget is an attribute here rather than
-- its own table -- at this cardinality a separate fact adds a relationship for
-- no analytical gain.
CREATE OR REPLACE VIEW vw_powerbi_dim_category AS
SELECT
    t.user_id,
    t.category                                     AS category_key,
    t.category                                     AS category_name,
    COUNT(*)                                       AS transaction_count,
    SUM(t.amount)                                  AS total_spend,
    ROUND(AVG(t.amount), 2)                        AS avg_transaction,
    MIN(t.date)                                    AS first_seen,
    MAX(t.date)                                    AS last_seen,
    b.monthly_limit                                AS monthly_budget
FROM transactions t
LEFT JOIN budgets b
       ON b.user_id = t.user_id
      AND b.category = t.category
GROUP BY t.user_id, t.category, b.monthly_limit;


-- ---------------------------------------------------------------------------
-- dim_merchant
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_powerbi_dim_merchant AS
SELECT
    t.user_id,
    m.display_name                                 AS merchant_key,
    m.display_name                                 AS merchant_name,
    m.default_category                             AS pinned_category,
    COUNT(*)                                       AS transaction_count,
    SUM(t.amount)                                  AS total_spend,
    ROUND(AVG(t.amount), 2)                        AS avg_transaction
FROM merchants m
JOIN transactions t ON t.merchant_id = m.id
GROUP BY t.user_id, m.display_name, m.default_category;


-- ---------------------------------------------------------------------------
-- fct_transactions -- the central fact table
-- ---------------------------------------------------------------------------
-- Grain: one row per transaction.
--
-- DISTINCT ON picks the most recent prediction per transaction. A plain join
-- would fan the fact table out to one row per prediction, silently multiplying
-- every SUM in the report -- the classic star-schema fan trap.
CREATE OR REPLACE VIEW vw_powerbi_fct_transactions AS
SELECT DISTINCT ON (t.id)
    t.id                                           AS transaction_key,
    t.user_id,
    t.date                                         AS date_key,
    t.category                                     AS category_key,
    COALESCE(m.display_name, '(unknown)')          AS merchant_key,
    t.description,
    t.amount,
    t.currency,
    t.source::text                                 AS source,
    (t.raw_transcript IS NOT NULL)                 AS is_voice_entry,
    p.confidence                                   AS categorization_confidence,
    p.accepted                                     AS categorization_accepted,
    p.predicted_category,
    p.corrected_to,
    p.model_version,
    -- Bucketed for a "how sure was the model" visual. Null means the row was
    -- entered manually and never went through the model at all -- which is
    -- different from a prediction that scored zero.
    CASE
        WHEN p.confidence IS NULL     THEN 'Not categorized by model'
        WHEN p.confidence >= 0.80     THEN 'High (>=0.80)'
        WHEN p.confidence >= 0.50     THEN 'Medium (0.50-0.80)'
        ELSE                               'Low (<0.50)'
    END                                            AS confidence_band
FROM transactions t
LEFT JOIN merchants m           ON m.id = t.merchant_id
LEFT JOIN category_predictions p ON p.transaction_id = t.id
ORDER BY t.id, p.created_at DESC;


-- ---------------------------------------------------------------------------
-- fct_monthly_spend -- pre-aggregated actuals
-- ---------------------------------------------------------------------------
-- The forecast fact is monthly, so actuals need to be monthly too for the two
-- to share an axis.
CREATE OR REPLACE VIEW vw_powerbi_fct_monthly_spend AS
SELECT
    user_id,
    DATE_TRUNC('month', date)::date                AS month_start,
    category                                       AS category_key,
    SUM(amount)                                    AS total_amount,
    COUNT(*)                                       AS transaction_count
FROM transactions
GROUP BY user_id, DATE_TRUNC('month', date), category;


-- ---------------------------------------------------------------------------
-- vw_powerbi_budget_variance
-- ---------------------------------------------------------------------------
-- A forecast is only actionable next to a target, so budget vs actual gets its
-- own view rather than being assembled in DAX.
CREATE OR REPLACE VIEW vw_powerbi_budget_variance AS
SELECT
    s.user_id,
    s.month_start,
    s.category_key,
    s.total_amount                                 AS actual_spend,
    b.monthly_limit                                AS budget,
    (b.monthly_limit - s.total_amount)             AS variance,
    CASE
        WHEN b.monthly_limit IS NULL OR b.monthly_limit = 0 THEN NULL
        ELSE ROUND(100.0 * s.total_amount / b.monthly_limit, 1)
    END                                            AS pct_of_budget,
    (b.monthly_limit IS NOT NULL AND s.total_amount > b.monthly_limit) AS is_over_budget
FROM vw_powerbi_fct_monthly_spend s
LEFT JOIN budgets b
       ON b.user_id = s.user_id
      AND b.category = s.category_key;


-- ---------------------------------------------------------------------------
-- vw_powerbi_categorization_quality
-- ---------------------------------------------------------------------------
-- Live model performance on real user behaviour: how often people kept what
-- the model suggested. Distinct from the offline evaluation against the fixed
-- corpus, and arguably the more honest number.
CREATE OR REPLACE VIEW vw_powerbi_categorization_quality AS
SELECT
    t.user_id,
    DATE_TRUNC('month', t.date)::date              AS month_start,
    p.model_version,
    COUNT(*)                                       AS predictions,
    COUNT(*) FILTER (WHERE p.accepted)             AS accepted,
    ROUND(AVG(p.confidence)::numeric, 4)           AS avg_confidence,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE p.accepted) / NULLIF(COUNT(*), 0),
        1
    )                                              AS acceptance_rate_pct
FROM category_predictions p
JOIN transactions t ON t.id = p.transaction_id
GROUP BY t.user_id, DATE_TRUNC('month', t.date), p.model_version;
