-- Synonym taxonomy cleanup for ecommerce query understanding.
-- Scope:
-- 1) Create missing searchable attributes.
-- 2) Remove noisy/non-searchable category aliases.
-- 3) Reassign high-value category terms into structured attributes.
-- 4) Seed missing critical synonyms for body jewelry search.
--
-- Run in staging first:
--   psql "$DATABASE_URL" -f backend/sql/migrations/20260316_synonym_taxonomy_cleanup.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) Ensure required searchable attributes exist
-- ---------------------------------------------------------------------------
INSERT INTO attribute_definitions (
    name, display_name, data_type, is_enabled, tier, display_order, is_multivalue, option_cap
)
VALUES
    ('body_location', 'Body Location', 'string', true, 'core', 45, false, 80),
    ('closure_type', 'Closure Type', 'string', true, 'core', 46, false, 60),
    ('diameter', 'Diameter', 'string', true, 'core', 47, false, 80),
    ('finish', 'Finish', 'string', true, 'core', 48, false, 60),
    ('stone', 'Stone', 'string', true, 'core', 49, false, 60),
    ('shape', 'Shape', 'string', true, 'secondary', 50, false, 80),
    ('style', 'Style', 'string', true, 'secondary', 51, false, 80)
ON CONFLICT (name) DO UPDATE
SET
    display_name = EXCLUDED.display_name,
    data_type = EXCLUDED.data_type,
    is_enabled = EXCLUDED.is_enabled;

-- ---------------------------------------------------------------------------
-- 2) Remove noisy/non-searchable category rows
-- ---------------------------------------------------------------------------
DELETE FROM facet_value_aliases f
USING attribute_definitions a
WHERE f.attribute_id = a.id
  AND a.name = 'category'
  AND lower(trim(f.canonical_value)) IN (
      'black friday',
      'clearance sale',
      'holiday season',
      'holiday season barbells',
      'christmas displays',
      'new products',
      'new colors',
      'new sizes',
      'display',
      'empty display',
      'empty body jewelry displays',
      'sold by pack',
      'sold by pair',
      'sold in bulks',
      'sold on displays',
      'sold per piece',
      'bulk',
      'others',
      'body jewelry part',
      'body jewelry parts',
      'piercing kits',
      'piercing tools',
      'selected 316l surgical steel body jewelry with jewel balls and half jewel balls',
      'new titanium g23 body jewelry with jewel balls and half jewel balls in multiple colors',
      '316l surgical steel hinged segment rings in various designs',
      '14k gold threadless push pin labrets with genuine stone',
      '925 sterling silver body jewelry displays with birthstones',
      'checkers',
      'cherries',
      'flowers',
      'hearts',
      'lizards',
      'skulls',
      'spider',
      'marijuana / mushrooms',
      'gay & lesbian pride',
      'ferido glued',
      'big gauge',
      'snake eyes',
      'loose'
  );

-- ---------------------------------------------------------------------------
-- 3) Reassign category -> structured attributes (keep canonical clean)
-- ---------------------------------------------------------------------------

-- 3a) Material reassignment
WITH target AS (
    SELECT id FROM attribute_definitions WHERE name = 'material'
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('925 Silver', '925 Sterling Silver'),
        ('925 Sterling Silver', '925 Sterling Silver'),
        ('Acrylic', 'Acrylic'),
        ('Gold', 'Gold'),
        ('Surgical Steel', 'Surgical Steel 316L'),
        ('Stainless Steel', 'Surgical Steel 316L'),
        ('Titanium G23', 'Titanium G23'),
        ('Titanium G5', 'Titanium G5'),
        ('Niobium', 'Niobium'),
        ('Silicone', 'Silicone'),
        ('Tungsten', 'Tungsten'),
        ('Rubber', 'Rubber'),
        ('Bio Flex / PTFE', 'PTFE/Bioflex'),
        ('Bioflex & PTFE', 'PTFE/Bioflex'),
        ('Wood, Bone, Horn & Stones', 'Organic')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    t.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target t
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- 3b) Threading reassignment
WITH target AS (
    SELECT id FROM attribute_definitions WHERE name = 'threading'
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('Internally Threaded', 'Internal'),
        ('Threadless', 'Threadless')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    t.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target t
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- 3c) Body location reassignment
WITH target AS (
    SELECT id FROM attribute_definitions WHERE name = 'body_location'
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('Belly Piercing', 'Navel'),
        ('Ear - Lobe Piercing', 'Lobe'),
        ('Eyebrow Piercing', 'Eyebrow'),
        ('Helix Piercing', 'Helix'),
        ('Intim Piercing', 'Intimate'),
        ('Lower Lip Piercing', 'Lip'),
        ('Nipple Piercing', 'Nipple'),
        ('Nose Bridge Piercing', 'Nose Bridge'),
        ('Nose Piercing', 'Nostril'),
        ('Septum Piercing', 'Septum'),
        ('Surface Piercing', 'Surface'),
        ('Tongue Piercing', 'Tongue'),
        ('Tragus Piercing', 'Tragus'),
        ('Upper Lip / Monroe', 'Monroe')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    t.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target t
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- 3d) Jewelry type reassignment
WITH target AS (
    SELECT id FROM attribute_definitions WHERE name = 'jewelry_type'
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('Ball Closure Rings', 'Captive Bead Ring'),
        ('Barbells', 'Straight Barbell'),
        ('Belly Banana', 'Curved Barbell'),
        ('Belly Bananas', 'Curved Barbell'),
        ('Bend it Yourself Nose Stud', 'Nose Stud'),
        ('Bend it Yourself Nose Studs', 'Nose Stud'),
        ('Circular Barbell', 'Circular Barbell'),
        ('Circular Barbells', 'Circular Barbell'),
        ('Circular Barbells and Bananas', 'Circular Barbell'),
        ('Dermal Anchors', 'Dermal Anchor'),
        ('Ear Ring/Ear Stud', 'Stud'),
        ('Ear Studs', 'Stud'),
        ('Eyebrow Bananas', 'Curved Barbell'),
        ('Fake Plug', 'Plug'),
        ('Fake Plugs', 'Plug'),
        ('Flesh Tunnel', 'Tunnel'),
        ('Flesh Tunnels', 'Tunnel'),
        ('Huggie', 'Huggie'),
        ('Huggies', 'Huggie'),
        ('Illusion Clips', 'Plug'),
        ('Labret', 'Labret'),
        ('Labrets', 'Labret'),
        ('Nose Bones', 'Nose Stud'),
        ('Nose Hoops', 'Ring'),
        ('Nose Screw & Nose Stud', 'Nose Stud'),
        ('Nose Screws & Nose Studs', 'Nose Stud'),
        ('Nose Screws and Nose Studs', 'Nose Stud'),
        ('Plugs', 'Plug'),
        ('Ring', 'Ring'),
        ('Segment and Seamless Ring', 'Segment Ring'),
        ('Seamless and Segment Rings', 'Segment Ring'),
        ('Spiral', 'Spiral'),
        ('Spirals and Twisters', 'Spiral'),
        ('Surface Barbells', 'Surface Barbell'),
        ('Taper', 'Taper'),
        ('Tapers and Expanders', 'Taper')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    t.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target t
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- 3e) Gauge reassignment from thickness labels
WITH target AS (
    SELECT id FROM attribute_definitions WHERE name = 'gauge'
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('0.6mm Thickness', '22g'),
        ('0.8mm Thickness', '20g'),
        ('1mm Thickness', '18g'),
        ('1.2mm Thickness', '16g'),
        ('1.6mm Thickness', '14g')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    t.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target t
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- 3f) Finish and stone reassignment
WITH target_finish AS (
    SELECT id FROM attribute_definitions WHERE name = 'finish'
),
seed_finish(raw_value, canonical_value) AS (
    VALUES
        ('PVD Plated', 'PVD'),
        ('Sterilized', 'Sterilized')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    tf.id,
    sf.raw_value,
    regexp_replace(lower(trim(sf.raw_value)), '\s+', ' ', 'g'),
    sf.canonical_value,
    regexp_replace(lower(trim(sf.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target_finish tf
CROSS JOIN seed_finish sf
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

WITH target_stone AS (
    SELECT id FROM attribute_definitions WHERE name = 'stone'
),
seed_stone(raw_value, canonical_value) AS (
    VALUES
        ('Opal Body Jewelry', 'Opal')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    ts.id,
    ss.raw_value,
    regexp_replace(lower(trim(ss.raw_value)), '\s+', ' ', 'g'),
    ss.canonical_value,
    regexp_replace(lower(trim(ss.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target_stone ts
CROSS JOIN seed_stone ss
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- ---------------------------------------------------------------------------
-- 4) Seed missing high-value synonyms used by shopper queries
-- ---------------------------------------------------------------------------

-- Jewelry type: key shopper phrases
WITH target AS (
    SELECT id FROM attribute_definitions WHERE name = 'jewelry_type'
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('labret stud', 'Labret'),
        ('labrets', 'Labret'),
        ('nose screw', 'Nose Screw'),
        ('nose stud', 'Nose Stud'),
        ('segment ring', 'Segment Ring'),
        ('hinged segment ring', 'Segment Ring'),
        ('clicker', 'Clicker Ring'),
        ('clicker ring', 'Clicker Ring'),
        ('captve ring', 'Captive Bead Ring'),
        ('captvie ring', 'Captive Bead Ring'),
        ('captive ring', 'Captive Bead Ring'),
        ('ball closure ring', 'Captive Bead Ring')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    t.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target t
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- Threading: common wording variants
WITH target AS (
    SELECT id FROM attribute_definitions WHERE name = 'threading'
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('internal thread', 'Internal'),
        ('internal', 'Internal'),
        ('externally threaded', 'External'),
        ('external thread', 'External'),
        ('push pin', 'Threadless'),
        ('push-fit', 'Threadless'),
        ('push fit', 'Threadless')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    t.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target t
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- Body location: likely shopper phrasing
WITH target AS (
    SELECT id FROM attribute_definitions WHERE name = 'body_location'
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('nostril', 'Nostril'),
        ('septum', 'Septum'),
        ('helix', 'Helix'),
        ('tragus', 'Tragus'),
        ('navel', 'Navel'),
        ('belly', 'Navel'),
        ('tongue', 'Tongue'),
        ('monroe', 'Monroe'),
        ('upper lip', 'Monroe'),
        ('industrial', 'Industrial')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    t.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target t
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- Diameter: useful ring-size intent terms
WITH target AS (
    SELECT id FROM attribute_definitions WHERE name = 'diameter'
),
seed(raw_value, canonical_value) AS (
    VALUES
        ('6 mm', '6mm'),
        ('8 mm', '8mm'),
        ('10 mm', '10mm'),
        ('12 mm', '12mm'),
        ('14 mm', '14mm')
)
INSERT INTO facet_value_aliases (
    attribute_id, raw_value, raw_value_norm, canonical_value, canonical_value_norm, is_active
)
SELECT
    t.id,
    s.raw_value,
    regexp_replace(lower(trim(s.raw_value)), '\s+', ' ', 'g'),
    s.canonical_value,
    regexp_replace(lower(trim(s.canonical_value)), '\s+', ' ', 'g'),
    true
FROM target t
CROSS JOIN seed s
ON CONFLICT (attribute_id, raw_value_norm) DO UPDATE
SET
    raw_value = EXCLUDED.raw_value,
    canonical_value = EXCLUDED.canonical_value,
    canonical_value_norm = EXCLUDED.canonical_value_norm,
    is_active = true;

-- ---------------------------------------------------------------------------
-- 5) Remove migrated category rows after reassignment/seed
-- ---------------------------------------------------------------------------
DELETE FROM facet_value_aliases f
USING attribute_definitions a
WHERE f.attribute_id = a.id
  AND a.name = 'category'
  AND lower(trim(f.canonical_value)) IN (
      '0.6mm thickness',
      '0.8mm thickness',
      '1mm thickness',
      '1.2mm thickness',
      '1.6mm thickness',
      '925 silver',
      '925 sterling silver',
      'acrylic',
      'gold',
      'surgical steel',
      'stainless steel',
      'titanium g23',
      'titanium g5',
      'niobium',
      'silicone',
      'tungsten',
      'rubber',
      'bio flex / ptfe',
      'bioflex & ptfe',
      'wood, bone, horn & stones',
      'internally threaded',
      'threadless',
      'opal body jewelry',
      'pvd plated',
      'sterilized',
      'ball closure rings',
      'barbells',
      'belly banana',
      'belly bananas',
      'bend it yourself nose stud',
      'bend it yourself nose studs',
      'circular barbell',
      'circular barbells',
      'circular barbells and bananas',
      'dermal anchors',
      'ear ring/ear stud',
      'ear studs',
      'eyebrow bananas',
      'fake plug',
      'fake plugs',
      'flesh tunnel',
      'flesh tunnels',
      'huggie',
      'huggies',
      'illusion clips',
      'labret',
      'labrets',
      'nose bones',
      'nose hoops',
      'nose screw & nose stud',
      'nose screws & nose studs',
      'nose screws and nose studs',
      'plugs',
      'ring',
      'segment and seamless ring',
      'seamless and segment rings',
      'spiral',
      'spirals and twisters',
      'surface barbells',
      'taper',
      'tapers and expanders',
      'belly piercing',
      'ear - lobe piercing',
      'eyebrow piercing',
      'helix piercing',
      'intim piercing',
      'lower lip piercing',
      'nipple piercing',
      'nose bridge piercing',
      'nose piercing',
      'septum piercing',
      'surface piercing',
      'tongue piercing',
      'tragus piercing',
      'upper lip / monroe'
  );

COMMIT;

-- ---------------------------------------------------------------------------
-- Verification queries (run after COMMIT)
-- ---------------------------------------------------------------------------
-- SELECT a.name, count(*) AS rows
-- FROM facet_value_aliases f
-- JOIN attribute_definitions a ON a.id = f.attribute_id
-- WHERE f.is_active
-- GROUP BY a.name
-- ORDER BY a.name;
--
-- SELECT f.id, a.name, f.canonical_value, f.raw_value
-- FROM facet_value_aliases f
-- JOIN attribute_definitions a ON a.id = f.attribute_id
-- WHERE a.name = 'category'
-- ORDER BY f.canonical_value, f.raw_value;
