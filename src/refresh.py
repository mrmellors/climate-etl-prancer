"""Refresh: pull new data from a source and append it safely.

Run it as your team:

    python src/refresh.py --team dasher --start 2025-09-01 --end 2025-10-01
    python src/refresh.py --team dasher --start 2025-09-01 --end 2025-10-01 --dry-run

The example "source" is the shared course table, so this file runs as soon as
sql/schema.sql has created your tables. Replace fetch() with code that downloads your
real source into data/raw/ and reads it, and change the staging table, checks, and merge
to match your tables.

What makes it safe to run again:
  - everything runs in one transaction, so a failure leaves your tables unchanged;
  - new rows go into a temporary staging table and are checked there first;
  - the merge matches rows on their natural key (station_id, date), so running the same
    refresh twice changes nothing the second time; and
  - each successful run is recorded in ingestion_runs.
"""

from __future__ import annotations

import argparse
from datetime import date

import psycopg

from course_db import connect

SOURCE = "course.observations (example source)"


def fetch(conn: psycopg.Connection, start: date, end: date) -> list[tuple]:
    """Return new rows as (station_id, date, tmax, tmin, precip) tuples.

    Example only: it reads the shared course table. Replace it with code that downloads
    and reads your source.
    """
    return conn.execute(
        """
        SELECT station_id, date, tmax, tmin, precip
        FROM course.observations
        WHERE date >= %s AND date < %s
        """,
        (start, end),
    ).fetchall()


def load_stage(conn: psycopg.Connection, rows: list[tuple]) -> None:
    """Copy the new rows into a staging table that disappears at the end of the run."""
    conn.execute(
        """
        CREATE TEMP TABLE stage_observations (
          station_id TEXT, date DATE, tmax NUMERIC, tmin NUMERIC, precip NUMERIC
        ) ON COMMIT DROP
        """
    )
    with conn.cursor() as cur:
        with cur.copy(
            "COPY stage_observations (station_id, date, tmax, tmin, precip) FROM STDIN"
        ) as copy:
            for row in rows:
                copy.write_row(row)


# Each check counts problem rows in the staging table. Add checks for your own data.
CHECKS = {
    "the same station and date appear twice": """
        SELECT count(*) FROM (
          SELECT station_id, date FROM stage_observations
          GROUP BY station_id, date HAVING count(*) > 1
        ) AS repeats""",
    "negative precipitation": "SELECT count(*) FROM stage_observations WHERE precip < 0",
    "tmax below tmin": "SELECT count(*) FROM stage_observations WHERE tmax < tmin",
    "station not in the station list": """
        SELECT count(*) FROM stage_observations AS s
        WHERE NOT EXISTS (
          SELECT 1 FROM course.stations AS c WHERE c.station_id = s.station_id
        )""",
}


def validate(conn: psycopg.Connection) -> list[str]:
    """Return a description of every failed check; an empty list means all passed."""
    problems = []
    for name, query in CHECKS.items():
        (count,) = conn.execute(query).fetchone()
        if count:
            problems.append(f"{name}: {count}")
    return problems


def merge(conn: psycopg.Connection) -> tuple[int, int]:
    """Move staged rows into the trusted tables. Return (rows inserted, rows updated)."""
    # Stations first, because observations refer to them. (Example: copied from the
    # shared course table.)
    conn.execute(
        """
        INSERT INTO stations (station_id, name, state, lat, lon, elevation)
        SELECT c.station_id, c.name, c.state, c.lat, c.lon, c.elevation
        FROM course.stations AS c
        WHERE c.station_id IN (SELECT station_id FROM stage_observations)
        ON CONFLICT (station_id) DO NOTHING
        """
    )
    (before,) = conn.execute("SELECT count(*) FROM observations").fetchone()
    changed = conn.execute(
        """
        INSERT INTO observations (station_id, date, tmax, tmin, precip)
        SELECT station_id, date, tmax, tmin, precip FROM stage_observations
        ON CONFLICT (station_id, date) DO UPDATE
          SET tmax = EXCLUDED.tmax, tmin = EXCLUDED.tmin, precip = EXCLUDED.precip
          WHERE (observations.tmax, observations.tmin, observations.precip)
                IS DISTINCT FROM (EXCLUDED.tmax, EXCLUDED.tmin, EXCLUDED.precip)
        RETURNING 1
        """
    ).rowcount
    (after,) = conn.execute("SELECT count(*) FROM observations").fetchone()
    inserted = after - before
    return inserted, changed - inserted


def log_run(conn: psycopg.Connection, staged: int, inserted: int, updated: int) -> None:
    conn.execute(
        """
        INSERT INTO ingestion_runs (source, rows_staged, rows_inserted, rows_updated)
        VALUES (%s, %s, %s, %s)
        """,
        (SOURCE, staged, inserted, updated),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull new data and append it safely.")
    parser.add_argument("--team", required=True, help="your team, e.g. dasher")
    parser.add_argument("--start", type=date.fromisoformat, required=True,
                        help="first date to load, YYYY-MM-DD")
    parser.add_argument("--end", type=date.fromisoformat, required=True,
                        help="day after the last date to load, YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true",
                        help="do everything, report the counts, then undo it")
    args = parser.parse_args()

    with connect(team=args.team) as conn:
        with conn.transaction():
            rows = fetch(conn, args.start, args.end)
            load_stage(conn, rows)
            problems = validate(conn)
            if problems:
                # Leaving the block with an exception rolls everything back.
                raise SystemExit("Validation failed; nothing was loaded:\n  "
                                 + "\n  ".join(problems))
            inserted, updated = merge(conn)
            log_run(conn, len(rows), inserted, updated)
            print(f"{len(rows)} rows staged, {inserted} inserted, {updated} updated.")
            if args.dry_run:
                print("Dry run: undoing all changes.")
                raise psycopg.Rollback()


if __name__ == "__main__":
    main()
