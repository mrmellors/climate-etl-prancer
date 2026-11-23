-- Question: Which counties have the highest reported
-- storm damage per resident?
-- Client use: Compare reported damage after accounting
-- for county population.
-- Row unit: One county.
-- Exclusions / caveats: Eight target states, 2015–2025;
-- only matched county FIPS, positive population;
-- nominal cumulative damage divided by the stored ACS population.
-- Test: sql/tests/t06-county-damage-per-capita.sql

SELECT
    d.county_fips,
    d.county_name,
    d.population,
    COUNT(*) AS storm_events,
    SUM(s.damage_property_usd) AS total_damage_usd,
    SUM(s.damage_property_usd) / d.population AS damage_per_person_usd
FROM prancer.storm_events AS s
JOIN prancer.county_demographics AS d
  ON s.county_fips = d.county_fips
WHERE s.state_fips IN ('48', '22', '01', '13', '12', '45', '37', '51')
  AND s.begin_ts >= DATE '2015-01-01'
  AND s.begin_ts < DATE '2026-01-01'
  AND d.population > 0
GROUP BY d.county_fips, d.county_name, d.population
ORDER BY damage_per_person_usd DESC NULLS LAST
LIMIT 25;
