-- Seed focused color normalization synonyms.
-- Scope:
-- - Attribute: color
-- - Normalize punctuation/spacing variants into stable canonical values
-- - Add a small curated set of high-value manual variants
--
-- Run:
--   python scripts/apply_sql_file.py sql/migrations/20260323_synonym_seed_color_normalization.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) Data-driven normalization from existing product values
-- ---------------------------------------------------------------------------
WITH attr AS (
    SELECT id
    FROM attribute_definitions
    WHERE lower(name) = 'color'
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
mapped AS (
    SELECT
        attribute_id,
        raw_value,
        raw_norm,
        CASE
            WHEN raw_norm LIKE 'assorted %' THEN NULL
            WHEN raw_norm LIKE 'mixed %' THEN NULL
            WHEN raw_norm LIKE 'random %' THEN NULL
            ELSE
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(
                                replace(replace(raw_norm, '-', ' '), '_', ' '),
                                '\s+',
                                ' ',
                                'g'
                            ),
                            '\s*colors?$',
                            '',
                            'g'
                        ),
                        '^colors?\s+',
                        '',
                        'g'
                    ),
                    '\s+',
                    ' ',
                    'g'
                )
        END AS canonical_norm
    FROM src
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
      AND length(canonical_norm) <= 40
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
    SELECT DISTINCT ON (u.attribute_id, u.raw_value_norm)
        u.attribute_id,
        u.raw_value,
        u.raw_value_norm,
        u.canonical_value,
        u.canonical_value_norm
    FROM (
    SELECT
        v.attribute_id,
        v.raw_value,
        v.raw_value_norm,
        v.canonical_value_norm AS canonical_value,
        v.canonical_value_norm AS canonical_value_norm
    FROM variant_rows v
    UNION ALL
    SELECT
        a.attribute_id,
        a.canonical_norm AS raw_value,
        a.canonical_norm AS raw_value_norm,
        a.canonical_norm AS canonical_value,
        a.canonical_norm AS canonical_value_norm
    FROM anchor_rows a
    ) u
    ORDER BY
        u.attribute_id,
        u.raw_value_norm,
        CASE WHEN u.raw_value = u.canonical_value THEN 1 ELSE 0 END,
        u.canonical_value_norm
) seeded
ON CONFLICT (attribute_id, raw_value_norm)
DO UPDATE SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = TRUE;

-- ---------------------------------------------------------------------------
-- 2) Curated high-value manual variants for shopper wording
-- ---------------------------------------------------------------------------
WITH attr AS (
    SELECT id
    FROM attribute_definitions
    WHERE lower(name) = 'color'
    LIMIT 1
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('rosegold', 'rose gold'),
        ('rose-gold', 'rose gold'),
        ('rose gold color', 'rose gold'),
        ('gold-tone', 'gold'),
        ('gold tone', 'gold'),
        ('silver-tone', 'silver'),
        ('silver tone', 'silver'),
        ('multi color', 'multicolor'),
        ('multi-color', 'multicolor'),
        ('colour black', 'black'),
        ('colour white', 'white')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    a.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    TRUE
FROM attr a
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm)
DO UPDATE SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = TRUE;

COMMIT;

-- ---------------------------------------------------------------------------
-- Verification
-- ---------------------------------------------------------------------------
-- SELECT
--   a.name,
--   COUNT(DISTINCT lower(btrim(f.canonical_value_norm))) FILTER (WHERE f.is_active) AS synonym_group_count
-- FROM attribute_definitions a
-- LEFT JOIN facet_value_aliases f ON f.attribute_id = a.id
-- WHERE lower(a.name) = 'color'
-- GROUP BY a.name;
