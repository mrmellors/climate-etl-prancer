-- Testing to see if the schema created the table and that the load_csv worked
SELECT *
FROM prancer.storm_events
LIMIT 10;

-- This lets you drop the table once we are done testing stuff
-- Can then try and reload more data possibly
SET ROLE prancer_write;
SET search_path = prancer, course, public;

DROP TABLE IF EXISTS prancer.storm_events;