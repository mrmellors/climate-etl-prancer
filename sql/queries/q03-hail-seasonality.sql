-- Question: When do hail events occur most often?
-- Client use: Identify peak months for seasonal underwriting and staffing.
-- Row unit: One state and calendar month.
-- Exclusions / caveats: Six Southeast states, 2015–2025; hail only.
-- Test: sql/tests/t03-hail-seasonality.sql

SELECT
    state_abbr,
    EXTRACT(MONTH FROM begin_ts) AS month,
    COUNT(*) AS hail_events,
    SUM(damage_property_usd) AS total_damage_usd
FROM prancer.storm_events
WHERE event_type = 'Hail'
  AND state_abbr IN ('TX', 'LA', 'FL', 'GA', 'SC', 'NC')
  AND begin_ts >= DATE '2015-01-01'
  AND begin_ts < DATE '2026-01-01'
GROUP BY state_abbr, EXTRACT(MONTH FROM begin_ts)
ORDER BY state_abbr, month;
