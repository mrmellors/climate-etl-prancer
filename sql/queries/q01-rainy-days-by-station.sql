-- Question: Which Pennsylvania stations reported rain on the most days in
--           September 2025?
-- Client use: (who would act on this answer, and what would they do?)
-- Row unit:   one station.
-- Excludes:   days with no precipitation value (not reported is not dry).
-- Test:       sql/tests/t01-rainy-days-match.sql
--
-- Example query on the shared course data; replace it with your own. Put each client
-- query in its own file, numbered q01, q02, ..., with this header filled in.

SELECT
  s.station_id,
  s.name,
  count(*) AS rainy_days
FROM course.observations AS o
JOIN course.stations AS s USING (station_id)
WHERE s.state = 'PA'
  AND o.date >= DATE '2025-09-01'
  AND o.date <  DATE '2025-10-01'
  AND o.precip > 0
GROUP BY s.station_id, s.name
ORDER BY rainy_days DESC, s.name
LIMIT 25;
