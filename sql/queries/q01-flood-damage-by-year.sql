-- Question: Which states have rising flood damage over time?
-- Client use: Compare annual reported property damage for underwriting review.
-- Row unit: One state and year.
-- Exclusions / caveats: Six Southeast states, 2015–2025; Flood and Flash Flood only; null property damage ignored.
-- Test: sql/tests/t01-flood-damage-by-year.sql

SELECT
    state_abbr,
    EXTRACT(YEAR FROM begin_ts) AS year,
    COUNT(*) AS flood_events,
    SUM(damage_property_usd) AS total_damage_usd
FROM prancer.storm_events
WHERE event_type IN ('Flood', 'Flash Flood')
  AND state_abbr IN ('TX', 'LA', 'FL', 'GA', 'SC', 'NC')
  AND begin_ts >= DATE '2015-01-01'
  AND begin_ts < DATE '2026-01-01'
  AND damage_property_usd IS NOT NULL
GROUP BY state_abbr, EXTRACT(YEAR FROM begin_ts)
ORDER BY state_abbr, year;
