"""Load data from a web API into a table in your team's schema.

The example asks the National Weather Service (NWS) for the latest observations
at Pittsburgh International Airport, station KPIT, and merges them into a table.
Replace it with your own source.

HOW TO USE THIS FILE
  1. Make the table first, in your team's sql/schema.sql, acting as your team.
     Its key says what counts as the same observation, so running this file
     again updates rows instead of copying them:

         CREATE TABLE nws_observations (
           station        TEXT,
           observed_at    TIMESTAMPTZ,
           temperature_c  NUMERIC,
           wind_speed_kmh NUMERIC,
           PRIMARY KEY (station, observed_at)
         );

  2. Change TEAM to your team, and put your own Andrew address in HEADERS. The
     NWS asks every program to say who is calling.
  3. From your repository's top folder, run it:
         python src/load_api.py
     It prints how many observations the API sent, and the table's row count
     before and after. Running it again is safe: the count stays the same,
     because rows already in the table are updated, not copied.

To use another API, change four things: the URL and params; the loop that
turns the response into rows (print one item of the response to find its
fields); the table; and the INSERT.

APIs that need a key, such as EIA, the Alternative Fuels Data Center, and the
Census Data API: sign up for a free key, and keep it out of your code and your
repository. A key is a password.
  1. Set it the way you set PGUSER (setup primer, Python setup):
         macOS:    add  export EIA_API_KEY="your-key"  to ~/.zshrc
         Windows:  setx EIA_API_KEY "your-key"
     Then quit and reopen VS Code.
  2. Read it in the code, and send it as one of the params:
         import os
         params = {"api_key": os.environ["EIA_API_KEY"], "frequency": "hourly"}
  DEMO_KEY works in place of a real key for a few test requests.
"""

import requests

from course_db import connect

TEAM = "dasher"                                                       # your team
URL = "https://api.weather.gov/stations/KPIT/observations"
HEADERS = {"User-Agent": "36-614 project (andrewid@andrew.cmu.edu)"}  # your address

# 1. Ask the API for the data. raise_for_status() stops the script here if the
#    API answered with an error, instead of loading nothing.
response = requests.get(URL, params={"limit": 100}, headers=HEADERS, timeout=30)
response.raise_for_status()
data = response.json()

# 2. Turn the response into rows: one tuple per observation, in the order of
#    the table's columns. A missing value comes back as None, which goes into
#    the table as NULL.
rows = []
for feature in data["features"]:
    obs = feature["properties"]
    rows.append((
        obs["stationId"],
        obs["timestamp"],
        obs["temperature"]["value"],   # degrees Celsius
        obs["windSpeed"]["value"],     # kilometers per hour
    ))
print(f"Read {len(rows)} observations from the API.")

# 3. Merge the rows, sending every value as a parameter. Nothing is saved until
#    this block ends without an error.
with connect(team=TEAM) as conn:
    (before,) = conn.execute("SELECT count(*) FROM nws_observations").fetchone()
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO nws_observations (station, observed_at, temperature_c, wind_speed_kmh)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (station, observed_at)
            DO UPDATE SET temperature_c = EXCLUDED.temperature_c,
                          wind_speed_kmh = EXCLUDED.wind_speed_kmh
            """,
            rows,
        )
    (after,) = conn.execute("SELECT count(*) FROM nws_observations").fetchone()
    print(f"nws_observations had {before} rows and now has {after}.")
