-- Question: Which Southeast weather stations were within 50 km
-- of Atlantic hurricane track points during 2020–2025?
-- Client use: Identify nearby weather stations for hurricane exposure review.
-- Row unit: One station and hurricane-track point pair.
-- Excludes: Tracks outside the Southeast coastal box,
-- stations outside the eight target states, and pairs farther
-- than 50 km. Nearby does not imply simultaneous observations.
-- Test: sql/tests/t08-hurricane-station-proximity.sql

WITH distances AS (
    SELECT
        s.station_id,
        s.name AS station_name,
        s.state_fips,
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
    WHERE s.state_fips IN ('48', '22', '01', '13', '12', '45', '37', '51')
      AND h.lat BETWEEN 24 AND 39.5
      AND h.lon BETWEEN -99 AND -74
      AND h.observed_at >= DATE '2020-01-01'
      AND h.observed_at < DATE '2026-01-01'
)
SELECT
    station_id,
    station_name,
    state_fips,
    storm_id,
    observed_at,
    max_wind_kt,
    round(km::numeric, 1) AS km
FROM distances
WHERE km <= 50
ORDER BY km, station_id
LIMIT 100;
