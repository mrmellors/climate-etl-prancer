-- Question: Which storm types have many fatalities relative to recorded property damage?
-- Client use: Flag storm hazards whose human impacts may be poorly reflected by property losses.
-- Row unit: One storm event type.
-- Exclusions / caveats: Six Southeast states, 2015–2025; zero and missing dollar estimates retained as recorded, without implying unreported loss is zero.
-- Test: sql/tests/t05-fatalities-vs-damage.sql

SELECT
    event_type,
    COUNT(*) AS events,
    SUM(deaths_direct + deaths_indirect) AS fatalities,
    SUM(damage_property_usd) AS reported_damage_usd
FROM prancer.storm_events
WHERE state_abbr IN ('TX', 'LA', 'FL', 'GA', 'SC', 'NC')
  AND begin_ts >= DATE '2015-01-01'
  AND begin_ts < DATE '2026-01-01'
GROUP BY event_type
HAVING SUM(deaths_direct + deaths_indirect) > 0
ORDER BY fatalities DESC, reported_damage_usd ASC NULLS LAST;
