-- Question: Which states have frequent floods versus costly floods?
-- Client use: Compare event frequency and average recorded damage per event.
-- Row unit: One state.
-- Exclusions / caveats: Eight target states, 2015–2025;
-- events without property damage are excluded from severity average.
-- Test: sql/tests/t02-flood-frequency-severity.sql

SELECT
    state_fips,
    COUNT(*) AS flood_events,
    SUM(damage_property_usd) AS total_damage_usd,
    AVG(damage_property_usd) AS avg_damage_per_reported_event_usd
FROM prancer.storm_events
WHERE event_type IN ('Flood', 'Flash Flood')
  AND state_fips IN ('48', '22', '01', '13', '12', '45', '37', '51')
  AND begin_ts >= DATE '2015-01-01'
  AND begin_ts < DATE '2026-01-01'
GROUP BY state_fips
ORDER BY total_damage_usd DESC NULLS LAST;
