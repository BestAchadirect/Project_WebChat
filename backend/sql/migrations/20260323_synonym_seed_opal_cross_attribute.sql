-- Ensure "opal" is recognized across relevant searchable attributes.
-- Safe to run multiple times.

WITH seed(attribute_name, raw_value, canonical_value) AS (
    VALUES
        ('color', 'opal', 'opal'),
        ('color', 'opal color', 'opal'),
        ('opal_color', 'opal', 'opal'),
        ('stone', 'opal', 'opal'),
        ('stone', 'synthetic opal', 'opal'),
        ('stone', 'lab opal', 'opal')
),
attrs AS (
    SELECT id, lower(name) AS name
    FROM attribute_definitions
    WHERE lower(name) IN ('color', 'opal_color', 'stone')
)
INSERT INTO facet_value_aliases (
    attribute_id,
    raw_value,
    raw_value_norm,
    canonical_value,
    canonical_value_norm,
    is_active
)
SELECT
    a.id AS attribute_id,
    s.raw_value,
    lower(btrim(s.raw_value)) AS raw_value_norm,
    s.canonical_value,
    lower(btrim(s.canonical_value)) AS canonical_value_norm,
    TRUE
FROM seed s
JOIN attrs a ON a.name = lower(s.attribute_name)
ON CONFLICT (attribute_id, raw_value_norm)
DO UPDATE SET
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = TRUE;
