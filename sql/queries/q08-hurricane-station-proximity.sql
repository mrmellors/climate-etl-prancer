-- Question: Which Southeast weather stations were within 50 km of Atlantic
--           hurricane track points during 2020-2025?
-- Client use: Identify nearby weather stations for hurricane exposure review.
-- Row unit: One station and hurricane-track point pair.
-- Excludes: Tracks outside the Southeast coastal box, stations outside the six
--           target states, and pairs farther than 50 km. Nearby does not mean
--           the station reported weather at the exact track-point time.
-- Test: sql/tests/t08-hurricane-station-proximity.sql
--
-- Based on Lecture 9's spatial-near-a-point example: first use a latitude/
-- longitude box, then calculate Haversine kilometers, then filter distance.

WITH distances AS (
    SELECT
        s.station_id,
        s.name AS station_name,
        s.state,
        h.storm_id,
        h.observed_at,
        h.max_wind_kt,
        2 * 6371 * asin(sqrt(
            power(sin(radians(s.lat - h.lat) / 2), 2)
          + cos(radians(h.lat)) * cos(radians(s.lat))
          * power(sin(radians(s.lon - h.lon) / 2), 2)
        )) AS km
    FROM prancer.stations AS s
    JOIN prancer.hurdat_tracks AS h
      ON s.lat BETWEEN h.lat - 0.50 AND h.lat + 0.50
     AND s.lon BETWEEN h.lon - 0.65 AND h.lon + 0.65
    WHERE s.state IN ('TX', 'LA', 'FL', 'GA', 'SC', 'NC')
      AND h.lat BETWEEN 24 AND 36
      AND h.lon BETWEEN -99 AND -75
      AND h.observed_at >= DATE '2020-01-01'
      AND h.observed_at < DATE '2026-01-01'
)
SELECT
    station_id,
    station_name,
    state,
    storm_id,
    observed_at,
    max_wind_kt,
    round(km::numeric, 1) AS km
FROM distances
WHERE km <= 50
ORDER BY km, station_id
LIMIT 100;
