-- Question: How many NOAA storm episodes exceed $1 billion in reported property damage by decade?
-- Client use: Track high-loss NOAA episodes, not official NOAA billion-dollar disasters.
-- Row unit: One decade.
-- Exclusions / caveats: Six Southeast states; episodes without an episode_id or reported property damage excluded; nominal USD; regional subset only.
-- Test: sql/tests/t04-billion-dollar-episodes.sql

WITH episode_damage AS (
    SELECT
        episode_id,
        MIN(EXTRACT(YEAR FROM begin_ts)) AS event_year,
        SUM(damage_property_usd) AS damage_usd
    FROM prancer.storm_events
    WHERE state_abbr IN ('TX', 'LA', 'FL', 'GA', 'SC', 'NC')
      AND episode_id IS NOT NULL
      AND damage_property_usd IS NOT NULL
    GROUP BY episode_id
)
SELECT
    FLOOR(event_year / 10) * 10 AS decade,
    COUNT(*) AS billion_dollar_episodes
FROM episode_damage
WHERE damage_usd >= 1000000000
GROUP BY FLOOR(event_year / 10) * 10
ORDER BY decade;
