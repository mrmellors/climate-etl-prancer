-- Question: Which states have rising flood damage over time?
-- Client use: Compare annual reported property damage for underwriting review.
-- Row unit: One state and year.
-- Exclusions / caveats: Eight target states, 2015–2025;
-- Flood and Flash Flood only; null property damage ignored.
-- Test: sql/tests/t01-flood-damage-by-year.sql

SELECT
    state_fips,
    EXTRACT(YEAR FROM begin_ts) AS year,
    COUNT(*) AS flood_events,
    SUM(damage_property_usd) AS total_damage_usd
FROM prancer.storm_events
WHERE event_type IN ('Flood', 'Flash Flood')
  AND state_fips IN ('48', '22', '01', '13', '12', '45', '37', '51')
  AND begin_ts >= DATE '2015-01-01'
  AND begin_ts < DATE '2026-01-01'
  AND damage_property_usd IS NOT NULL
GROUP BY state_fips, EXTRACT(YEAR FROM begin_ts)
ORDER BY state_fips, year;
