-- Test for q01: count rainy days a second, independent way and compare.
-- Passes when it returns zero rows. Any row returned is a station where the two counts
-- disagree.
--
-- Every test in this folder follows the same rule: zero rows means it passed. Name each
-- test t01, t02, ... and say which query or table it checks.

WITH by_join AS (
  SELECT o.station_id, count(*) AS rainy_days
  FROM course.observations AS o
  JOIN course.stations AS s USING (station_id)
  WHERE s.state = 'PA'
    AND o.date >= DATE '2025-09-01' AND o.date < DATE '2025-10-01'
    AND o.precip > 0
  GROUP BY o.station_id
),
by_filter AS (
  SELECT station_id, count(*) FILTER (WHERE precip > 0) AS rainy_days
  FROM course.observations
  WHERE station_id IN (SELECT station_id FROM course.stations WHERE state = 'PA')
    AND date >= DATE '2025-09-01' AND date < DATE '2025-10-01'
  GROUP BY station_id
  HAVING count(*) FILTER (WHERE precip > 0) > 0
)
SELECT
  station_id,
  j.rainy_days AS by_join,
  f.rainy_days AS by_filter
FROM by_join AS j
FULL JOIN by_filter AS f USING (station_id)
WHERE j.rainy_days IS DISTINCT FROM f.rainy_days;
