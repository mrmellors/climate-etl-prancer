-- Test for q08-hurricane-station-proximity.sql.
-- A one-degree latitude separation should be about 111.2 km.
-- Also check that the prefilter box does not exclude a station within
-- 50 km of one representative eligible hurricane track point.
-- Returns zero rows when the checks pass.

WITH one_degree AS (
    SELECT 2 * 6371 * asin(sqrt(
        power(sin(radians(41.0 - 40.0) / 2), 2)
      + cos(radians(40.0)) * cos(radians(41.0))
      * power(sin(radians(-80.0 - -80.0) / 2), 2)
    )) AS km
),
point AS (
    SELECT lat, lon
    FROM prancer.hurdat_tracks
    WHERE lat BETWEEN 24 AND 36
      AND lon BETWEEN -99 AND -75
      AND observed_at >= DATE '2020-01-01'
      AND observed_at < DATE '2026-01-01'
    ORDER BY observed_at, track_id
    LIMIT 1
),
every_distance AS (
    SELECT
        s.station_id,
        s.lat,
        s.lon,
        p.lat AS track_lat,
        p.lon AS track_lon,
        2 * 6371 * asin(sqrt(
            power(sin(radians(s.lat - p.lat) / 2), 2)
          + cos(radians(p.lat)) * cos(radians(s.lat))
          * power(sin(radians(s.lon - p.lon) / 2), 2)
        )) AS km
    FROM prancer.stations AS s
    CROSS JOIN point AS p
    WHERE s.state IN ('TX', 'LA', 'FL', 'GA', 'SC', 'NC')
)
SELECT 'one degree of latitude not about 111.2 km' AS problem
FROM one_degree
WHERE abs(km - 111.2) > 0.1
UNION ALL
SELECT 'station inside 50 km excluded by box: ' || station_id
FROM every_distance
WHERE km <= 50
  AND NOT (lat BETWEEN track_lat - 0.50 AND track_lat + 0.50
       AND lon BETWEEN track_lon - 0.65 AND track_lon + 0.65);
