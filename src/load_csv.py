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

from course_db import connect

TEAM = "dasher"                                      # your team
CSV_FILE = Path("data/raw/pittsburgh-oct-2025.csv")  # the file to load

# Nothing is saved until this block ends without an error. If any row fails,
# no rows are loaded.
with connect(team=TEAM) as conn:
    with conn.cursor() as cur:
        with cur.copy("COPY pittsburgh_oct FROM STDIN (FORMAT csv, HEADER true)") as copy:
            with open(CSV_FILE, "rb") as f:
                for line in f:
                    copy.write(line)
        print(f"Loaded {cur.rowcount} rows from {CSV_FILE}.")
