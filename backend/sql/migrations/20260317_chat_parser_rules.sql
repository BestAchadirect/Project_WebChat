-- DB-driven parser rules for chat detail query parser.
-- Safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS chat_parser_rules (
    id BIGSERIAL PRIMARY KEY,
    rule_group VARCHAR(32) NOT NULL,
    target_key VARCHAR(100) NOT NULL,
    pattern TEXT NOT NULL,
    canonical_value TEXT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_parser_rules_group_target_pattern
    ON chat_parser_rules (rule_group, target_key, pattern);

CREATE INDEX IF NOT EXISTS ix_chat_parser_rules_group_priority
    ON chat_parser_rules (rule_group, priority, id);

-- Requested field patterns.
INSERT INTO chat_parser_rules (rule_group, target_key, pattern, priority, is_active) VALUES
    ('requested_field', 'price', '\bprice\b', 10, TRUE),
    ('requested_field', 'price', '\bcost\b', 11, TRUE),
    ('requested_field', 'price', '\bhow much\b', 12, TRUE),
    ('requested_field', 'stock', '\bstock\b', 10, TRUE),
    ('requested_field', 'stock', '\bavailability\b', 11, TRUE),
    ('requested_field', 'stock', '\bin stock\b', 12, TRUE),
    ('requested_field', 'stock', '\bout of stock\b', 13, TRUE),
    ('requested_field', 'stock', '\bavailable\b', 14, TRUE),
    ('requested_field', 'image', '\bimage\b', 10, TRUE),
    ('requested_field', 'image', '\bpicture\b', 11, TRUE),
    ('requested_field', 'image', '\bphoto\b', 12, TRUE),
    ('requested_field', 'image', '\bpic\b', 13, TRUE),
    ('requested_field', 'attributes', '\battribute\b', 10, TRUE),
    ('requested_field', 'attributes', '\battributes\b', 11, TRUE),
    ('requested_field', 'attributes', '\bspec\b', 12, TRUE),
    ('requested_field', 'attributes', '\bspecs\b', 13, TRUE),
    ('requested_field', 'attributes', '\bdetails\b', 14, TRUE),
    ('requested_field', 'attributes', '\bmaterial\b', 15, TRUE),
    ('requested_field', 'attributes', '\bcolor\b', 16, TRUE),
    ('requested_field', 'attributes', '\bfinish\b', 17, TRUE),
    ('requested_field', 'attributes', '\bgauge\b', 18, TRUE),
    ('requested_field', 'attributes', '\bthreading\b', 19, TRUE),
    ('requested_field', 'attributes', '\bcategory\b', 20, TRUE),
    ('requested_field', 'attributes', '\bdesign\b', 21, TRUE),
    ('requested_field', 'attributes', '\bshape\b', 22, TRUE),
    ('requested_field', 'attributes', '\blength\b', 23, TRUE),
    ('requested_field', 'attributes', '\bsize\b', 24, TRUE),
    ('requested_field', 'attributes', '\bouter diameter\b', 25, TRUE),
    ('requested_field', 'attributes', '\bdiameter\b', 26, TRUE),
    ('requested_field', 'attributes', '\bopal color\b', 27, TRUE),
    ('requested_field', 'attributes', '\bpearl color\b', 28, TRUE),
    ('requested_field', 'attributes', '\bcrystal color\b', 29, TRUE),
    ('requested_field', 'attributes', '\bcz color\b', 30, TRUE),
    ('requested_field', 'attributes', '\bring size\b', 31, TRUE),
    ('requested_field', 'attributes', '\brack\b', 32, TRUE)
ON CONFLICT (rule_group, target_key, pattern) DO NOTHING;

-- Lexical detection order. Actual matching terms come from facet_value_aliases.
INSERT INTO chat_parser_rules (rule_group, target_key, pattern, priority, is_active) VALUES
    ('detection_order', 'jewelry_type', '.*', 10, TRUE),
    ('detection_order', 'material', '.*', 20, TRUE),
    ('detection_order', 'threading', '.*', 30, TRUE),
    ('detection_order', 'finish', '.*', 40, TRUE),
    ('detection_order', 'design', '.*', 50, TRUE),
    ('detection_order', 'color', '.*', 60, TRUE)
ON CONFLICT (rule_group, target_key, pattern) DO NOTHING;

-- Value extraction patterns.
INSERT INTO chat_parser_rules (rule_group, target_key, pattern, priority, is_active) VALUES
    ('value_extract', 'category', '\bcategory(?: is|=| of| for| in)?\s+(?P<value>[a-z0-9][a-z0-9&/;,\- ]{1,60})\b', 10, TRUE),
    ('value_extract', 'design', '\bdesign(?: is|=| of| with)?\s+(?P<value>[a-z0-9][a-z0-9&/\- ]{1,40})\b', 10, TRUE),
    ('value_extract', 'design', '\bwith\s+(?P<value>[a-z0-9][a-z0-9&/\- ]{1,30})\s+design\b', 11, TRUE),
    ('value_extract', 'design', '\b(?P<value>[a-z0-9][a-z0-9&/\- ]{1,20})\s+shape\b', 12, TRUE),
    ('value_extract', 'design', '\b(?P<value>[a-z0-9][a-z0-9&/\- ]{1,20})-shaped\b', 13, TRUE),
    ('value_extract', 'length', '\blength(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches)?)\b', 10, TRUE),
    ('value_extract', 'length', '\b(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\s+length\b', 11, TRUE),
    ('value_extract', 'size', '\bsize(?: is|=| of)?\s+(?P<value>[a-z0-9.]+(?:\s*(?:mm|cm|in|inch|inches))?)\b', 10, TRUE),
    ('value_extract', 'outer_diameter', '\bouter diameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b', 10, TRUE),
    ('value_extract', 'outer_diameter', '\b(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\s+outer diameter\b', 11, TRUE),
    ('value_extract', 'outer_diameter', '\bdiameter(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b', 12, TRUE),
    ('value_extract', 'ring_size', '\bring size(?: is|=| of)?\s+(?P<value>[a-z0-9.]+)\b', 10, TRUE),
    ('value_extract', 'pincher_size', '\bpincher size(?: is|=| of)?\s+(?P<value>[a-z0-9.]+(?:\s*(?:mm|cm))?)\b', 10, TRUE),
    ('value_extract', 'height', '\bheight(?: is|=| of)?\s+(?P<value>\d{1,3}(?:\.\d+)?\s*(?:mm|cm|in|inch|inches))\b', 10, TRUE),
    ('value_extract', 'packing_option', '\bpacking option(?: is|=| of)?\s+(?P<value>[a-z0-9][a-z0-9/\- ]{1,30})\b', 10, TRUE),
    ('value_extract', 'packing_option', '\bpack(?:ing)?(?: option)?\s+(?P<value>[a-z0-9][a-z0-9/\- ]{1,30})\b', 11, TRUE),
    ('value_extract', 'size_in_pack', '\bsize in pack(?: is|=| of)?\s+(?P<value>[a-z0-9.]+)\b', 10, TRUE),
    ('value_extract', 'size_in_pack', '\bpack size(?: is|=| of)?\s+(?P<value>[a-z0-9.]+)\b', 11, TRUE),
    ('value_extract', 'quantity_in_bulk', '\bquantity in bulk(?: is|=| of)?\s+(?P<value>\d{1,5})\b', 10, TRUE),
    ('value_extract', 'quantity_in_bulk', '\bbulk qty(?: is|=| of)?\s+(?P<value>\d{1,5})\b', 11, TRUE),
    ('value_extract', 'quantity_in_bulk', '\bbulk quantity(?: is|=| of)?\s+(?P<value>\d{1,5})\b', 12, TRUE),
    ('value_extract', 'rack', '\brack(?: is|=| number| no\.?)?\s+(?P<value>[a-z0-9\-]{1,20})\b', 10, TRUE),
    ('value_extract', 'opal_color', '\b(?P<value>black|white|clear|blue|red|green|purple|pink|yellow|orange|silver|gold|rose gold)\s+opal color\b', 10, TRUE),
    ('value_extract', 'pearl_color', '\bpearl color(?: is|=| of)?\s+(?P<value>[a-z ]{2,20})\b', 10, TRUE),
    ('value_extract', 'pearl_color', '\b(?P<value>[a-z ]{2,20})\s+pearl\b', 11, TRUE),
    ('value_extract', 'crystal_color', '\bcrystal color(?: is|=| of)?\s+(?P<value>[a-z ]{2,20})\b', 10, TRUE),
    ('value_extract', 'crystal_color', '\b(?P<value>[a-z ]{2,20})\s+crystal\b', 11, TRUE),
    ('value_extract', 'cz_color', '\bcz color(?: is|=| of)?\s+(?P<value>[a-z ]{2,20})\b', 10, TRUE),
    ('value_extract', 'cz_color', '\b(?P<value>[a-z ]{2,20})\s+cz\b', 11, TRUE),
    ('value_extract', 'cz_color', '\bcubic zirconia color(?: is|=| of)?\s+(?P<value>[a-z ]{2,20})\b', 12, TRUE)
ON CONFLICT (rule_group, target_key, pattern) DO NOTHING;

COMMIT;
