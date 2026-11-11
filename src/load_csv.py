"""Load a CSV file into a table in your team's schema.

The example loads Pittsburgh's daily weather for October 2025 from a file
in data/raw/. Replace it with your own file.

HOW TO USE THIS FILE
  1. Make the table first, in your team's sql/schema.sql, acting as your team.
     List its columns in the same order as the file's columns:

         CREATE TABLE pittsburgh_oct (
           station_id TEXT,
           date       DATE,
           tmax       NUMERIC,
           tmin       NUMERIC,
           precip     NUMERIC
         );

  2. Put the file in data/raw/. Git ignores that folder, so the file stays out
     of your repository; write down in the runbook where it came from.
  3. Change three things below: TEAM, CSV_FILE, and the table's name in the
     COPY line.
  4. From your repository's top folder, run it once:
         python src/load_csv.py
     It prints the number of rows it loaded. Check that number against the
     file: its line count, minus the header line.

Run it once per file. A second run loads every row again: the table gets
copies, or the run fails with a duplicate key if the table has one. For the
nightly refresh, load into a staging table and merge, as src/refresh.py does.

When the file and the table don't match:
  - The file has no header line: change HEADER true to HEADER false.
  - The table has columns the file doesn't, such as an ID or a load time:
    list the file's columns after the table's name,
        COPY pittsburgh_oct (station_id, date, tmax, tmin, precip) FROM STDIN ...
  - The file has columns you don't want: load every column into a raw table
    first, then copy the ones you want with INSERT ... SELECT.
  - The file ends in .gz: add "import gzip" at the top, and change
    open(CSV_FILE, "rb") to gzip.open(CSV_FILE, "rb").
  - A value doesn't fit its column, such as a date that doesn't exist: no rows
    load, and the error names the line and the column.
"""

from pathlib import Path
from io import StringIO
import pandas as pd

from course_db import connect

TEAM = "prancer"                                      # your team
 # the file to load downloaded seperately for this little example
 # from: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/
CSV_FILE = Path("data/raw/storms_2025.csv.gz") 

# Select some NOAA columns to load
columns = [
    "EVENT_ID",
    "EPISODE_ID",
    "STATE",
    "EVENT_TYPE",
    "BEGIN_YEARMONTH",
    "DAMAGE_PROPERTY",
    "DEATHS_DIRECT",
    "INJURIES_DIRECT"
]

# Read the compressed CSV (the .gz part)
df = pd.read_csv(
    CSV_FILE,
    compression="gzip",
    usecols=columns
)

# Match the SQL column order
df = df[columns]

# Convert column names to lowercase
df.columns = df.columns.str.lower()

print(f"Found {len(df)} storm events")

# Prepare CSV data for PostgreSQL COPY
# normally we would pass a file output to .to_csv
# here we use buffer which kind of acts as a temporary file
# we do this so that we don't have to unpack the .gz file and have the csv locally as well
buffer = StringIO()
df.to_csv(buffer, index=False, na_rep="")
buffer.seek(0)

# Load into the team's database
# Nothing is saved until this block ends without an error. If any row fails,
# no rows are loaded.
with connect(team=TEAM) as conn:
    with conn.cursor() as cur:
        with cur.copy(
            """
            COPY storm_events (
                event_id, episode_id, state,
                event_type, begin_yearmonth,
                damage_property, deaths_direct,
                injuries_direct
            )
            FROM STDIN (FORMAT csv, HEADER true)
            """
        ) as copy:
            copy.write(buffer.getvalue().encode("utf-8"))

print("Storm Events data loaded successfully!")
