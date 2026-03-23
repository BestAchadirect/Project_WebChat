-- Seed synonym rules for size + outer_diameter.
-- Goals:
-- 1) Normalize noisy raw values into cleaner canonical values.
-- 2) Insert alias rows for raw -> canonical mappings.
-- 3) Insert canonical anchor rows so groups appear in Synonym Rules UI.
--
-- Run:
--   psql "$DATABASE_URL" -f backend/sql/migrations/20260323_synonym_seed_size_outer_diameter.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- OUTER DIAMETER
-- ---------------------------------------------------------------------------
WITH attr AS (
    SELECT id
    FROM attribute_definitions
    WHERE lower(name) = 'outer_diameter'
    LIMIT 1
),
src AS (
    SELECT
        pav.attribute_id,
        btrim(COALESCE(pav.value, '')) AS raw_value,
        lower(btrim(COALESCE(pav.value_norm, pav.value, ''))) AS raw_norm
    FROM product_attribute_values pav
    JOIN attr a ON a.id = pav.attribute_id
    WHERE COALESCE(pav.value_norm, pav.value) IS NOT NULL
      AND btrim(COALESCE(pav.value_norm, pav.value)) <> ''
),
cleaned AS (
    SELECT
        attribute_id,
        raw_value,
        regexp_replace(raw_norm, '\s+', ' ', 'g') AS raw_norm
    FROM src
),
mapped AS (
    SELECT
        attribute_id,
        raw_value,
        raw_norm,
        CASE
            WHEN raw_norm LIKE 'assorted %' THEN NULL
            ELSE
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            CASE
                                WHEN raw_norm ~ '([0-9]+(?:\.[0-9]+)?\s*(?:mm|cm|in|"))'
                                    THEN regexp_replace(
                                        raw_norm,
                                        '.*?([0-9]+(?:\.[0-9]+)?\s*(?:mm|cm|in|")).*',
                                        '\1'
                                    )
                                ELSE regexp_replace(raw_norm, '^(outer diameter|diameter|od)\s*[:=-]?\s*', '')
                            END,
                            '\s+',
                            ' ',
                            'g'
                        ),
                        '([0-9]+(?:\.[0-9]+)?)\s*(mm|cm|in)\b',
                        '\1\2',
                        'g'
                    ),
                    '\s+"$',
                    '"'
                )
        END AS canonical_norm
    FROM cleaned
),
variant_rows AS (
    SELECT DISTINCT
        attribute_id,
        raw_value,
        raw_norm AS raw_value_norm,
        canonical_norm AS canonical_value_norm
    FROM mapped
    WHERE canonical_norm IS NOT NULL
      AND canonical_norm <> ''
      AND canonical_norm <> raw_norm
),
anchor_rows AS (
    SELECT DISTINCT
        attribute_id,
        canonical_norm
    FROM mapped
    WHERE canonical_norm IS NOT NULL
      AND canonical_norm <> ''
      AND length(canonical_norm) <= 32
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    seeded.attribute_id,
    seeded.raw_value,
    seeded.raw_value_norm,
    seeded.canonical_value,
    seeded.canonical_value_norm,
    TRUE
FROM (
    SELECT
        v.attribute_id,
        v.raw_value,
        v.raw_value_norm,
        v.canonical_value_norm AS canonical_value,
        v.canonical_value_norm AS canonical_value_norm
    FROM variant_rows v
    WHERE NOT EXISTS (
        SELECT 1
        FROM facet_value_aliases f
        WHERE f.attribute_id = v.attribute_id
          AND lower(btrim(f.raw_value_norm)) = lower(btrim(v.raw_value_norm))
          AND lower(btrim(f.canonical_value_norm)) = lower(btrim(v.canonical_value_norm))
    )
    UNION ALL
    SELECT
        a.attribute_id,
        a.canonical_norm AS raw_value,
        a.canonical_norm AS raw_value_norm,
        a.canonical_norm AS canonical_value,
        a.canonical_norm AS canonical_value_norm
    FROM anchor_rows a
    WHERE NOT EXISTS (
        SELECT 1
        FROM facet_value_aliases f
        WHERE f.attribute_id = a.attribute_id
          AND lower(btrim(f.raw_value_norm)) = lower(btrim(a.canonical_norm))
    )
) seeded;

-- ---------------------------------------------------------------------------
-- SIZE
-- ---------------------------------------------------------------------------
WITH attr AS (
    SELECT id
    FROM attribute_definitions
    WHERE lower(name) = 'size'
    LIMIT 1
),
src AS (
    SELECT
        pav.attribute_id,
        btrim(COALESCE(pav.value, '')) AS raw_value,
        lower(btrim(COALESCE(pav.value_norm, pav.value, ''))) AS raw_norm
    FROM product_attribute_values pav
    JOIN attr a ON a.id = pav.attribute_id
    WHERE COALESCE(pav.value_norm, pav.value) IS NOT NULL
      AND btrim(COALESCE(pav.value_norm, pav.value)) <> ''
),
cleaned AS (
    SELECT
        attribute_id,
        raw_value,
        regexp_replace(raw_norm, '\s+', ' ', 'g') AS raw_norm
    FROM src
),
mapped AS (
    SELECT
        attribute_id,
        raw_value,
        raw_norm,
        CASE
            WHEN raw_norm LIKE 'assorted %' THEN NULL
            WHEN raw_norm LIKE '% with %' THEN NULL
            WHEN raw_norm LIKE '%thickness%' THEN NULL
            ELSE
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(raw_norm, '^size\s*[:=-]?\s*', ''),
                            '\s+',
                            ' ',
                            'g'
                        ),
                        '([0-9]+(?:\.[0-9]+)?)\s*(mm|cm|in)\b',
                        '\1\2',
                        'g'
                    ),
                    '\s+"$',
                    '"'
                )
        END AS canonical_norm
    FROM cleaned
),
variant_rows AS (
    SELECT DISTINCT
        attribute_id,
        raw_value,
        raw_norm AS raw_value_norm,
        canonical_norm AS canonical_value_norm
    FROM mapped
    WHERE canonical_norm IS NOT NULL
      AND canonical_norm <> ''
      AND canonical_norm <> raw_norm
),
anchor_rows AS (
    SELECT DISTINCT
        attribute_id,
        canonical_norm
    FROM mapped
    WHERE canonical_norm IS NOT NULL
      AND canonical_norm <> ''
      AND length(canonical_norm) <= 32
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    seeded.attribute_id,
    seeded.raw_value,
    seeded.raw_value_norm,
    seeded.canonical_value,
    seeded.canonical_value_norm,
    TRUE
FROM (
    SELECT
        v.attribute_id,
        v.raw_value,
        v.raw_value_norm,
        v.canonical_value_norm AS canonical_value,
        v.canonical_value_norm AS canonical_value_norm
    FROM variant_rows v
    WHERE NOT EXISTS (
        SELECT 1
        FROM facet_value_aliases f
        WHERE f.attribute_id = v.attribute_id
          AND lower(btrim(f.raw_value_norm)) = lower(btrim(v.raw_value_norm))
          AND lower(btrim(f.canonical_value_norm)) = lower(btrim(v.canonical_value_norm))
    )
    UNION ALL
    SELECT
        a.attribute_id,
        a.canonical_norm AS raw_value,
        a.canonical_norm AS raw_value_norm,
        a.canonical_norm AS canonical_value,
        a.canonical_norm AS canonical_value_norm
    FROM anchor_rows a
    WHERE NOT EXISTS (
        SELECT 1
        FROM facet_value_aliases f
        WHERE f.attribute_id = a.attribute_id
          AND lower(btrim(f.raw_value_norm)) = lower(btrim(a.canonical_norm))
    )
) seeded;

COMMIT;

-- ---------------------------------------------------------------------------
-- Verification
-- ---------------------------------------------------------------------------
-- SELECT
--   a.name,
--   COUNT(DISTINCT lower(btrim(f.canonical_value_norm))) FILTER (WHERE f.is_active) AS synonym_group_count
-- FROM attribute_definitions a
-- LEFT JOIN facet_value_aliases f ON f.attribute_id = a.id
-- WHERE lower(a.name) IN ('size', 'outer_diameter')
-- GROUP BY a.name
-- ORDER BY a.name;
