-- Ensure parser detection order includes stone/opal_color so plain opal-like queries
-- can be resolved via DB alias map before fallback.
-- Safe to run multiple times.

INSERT INTO chat_parser_rules (rule_group, target_key, pattern, priority, is_active)
SELECT 'detection_order', 'stone', '', 64, TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM chat_parser_rules
    WHERE lower(rule_group) = 'detection_order'
      AND lower(target_key) = 'stone'
      AND is_active IS TRUE
);

INSERT INTO chat_parser_rules (rule_group, target_key, pattern, priority, is_active)
SELECT 'detection_order', 'opal_color', '', 65, TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM chat_parser_rules
    WHERE lower(rule_group) = 'detection_order'
      AND lower(target_key) = 'opal_color'
      AND is_active IS TRUE
);
