"""Refresh Atlantic HURDAT2 storm headers and track observations."""

import csv
import re
from io import StringIO

import pandas as pd
import requests
from course_db import connect

BASE_URL = "https://www.nhc.noaa.gov/data/hurdat/"
MIN_YEAR = 1980  # Matches project's HURDAT2 coverage; use 1851 for full history.
STORM_COLUMNS = ["storm_id", "storm_name", "basin", "cyclone_number", "season_year", "num_track_points"]
TRACK_COLUMNS = [
    "storm_id", "observed_at", "record_identifier", "system_status",
    "lat", "lon", "max_wind_kt", "min_pressure_mb",
]


def transform_hurricanes(content):
    """Separate storm headers and observations, then clean the track columns."""
    storms, tracks = [], []
    storm_id = None

    # Each storm header is followed by its comma-separated observations.
    for row in csv.reader(StringIO(content), skipinitialspace=True):
        if not row:
            continue
        if re.fullmatch(r"AL\d{6}", row[0]):
            storm_id = row[0]
            storms.append([
                storm_id, row[1].strip(), storm_id[:2],
                int(storm_id[2:4]), int(storm_id[-4:]), int(row[2]),
            ])
        else:
            if storm_id is None or len(row) < 8:
                raise ValueError("Invalid HURDAT2 observation")
            tracks.append([storm_id, *row[:8]])

    storms = pd.DataFrame(storms, columns=STORM_COLUMNS)
    storms = storms.loc[storms["season_year"] >= MIN_YEAR].copy()
    tracks = pd.DataFrame(tracks, columns=[
        "storm_id", "date", "time", "record_identifier", "system_status",
        "lat", "lon", "max_wind_kt", "min_pressure_mb",
    ])
    tracks = tracks.loc[tracks["storm_id"].isin(storms["storm_id"])].copy()

    for col in ["date", "time", "record_identifier", "system_status", "lat", "lon"]:
        tracks[col] = tracks[col].astype("string").str.strip()

    tracks["observed_at"] = pd.to_datetime(
        tracks["date"] + tracks["time"].str.zfill(4),
        format="%Y%m%d%H%M", utc=True,
    )
    tracks["record_identifier"] = tracks["record_identifier"].replace("", "R")

    # South and west coordinates are negative.
    for col in ["lat", "lon"]:
        values = tracks[col]
        if not values.str.fullmatch(r"\d+(?:\.\d+)?[NSEW]").all():
            raise ValueError(f"Invalid HURDAT2 {col} coordinate")
        tracks[col] = pd.to_numeric(values.str[:-1])
        tracks.loc[values.str[-1].isin(["S", "W"]), col] *= -1

    # NOAA uses -999 for missing measurements.
    for col in ["max_wind_kt", "min_pressure_mb"]:
        tracks[col] = pd.to_numeric(tracks[col]).replace([-999, -99], pd.NA).astype("Int64")

    return storms, tracks[TRACK_COLUMNS]


def load_stage(conn, storms, tracks):
    """Load transformed storms and tracks into temporary staging tables."""
    for table, columns, df in [
        ("hurdat_storms", STORM_COLUMNS, storms),
        ("hurdat_tracks", TRACK_COLUMNS, tracks),
    ]:
        conn.execute(f"""
            CREATE TEMP TABLE stage_{table} (
                LIKE prancer.{table} INCLUDING DEFAULTS
            ) ON COMMIT DROP
        """)

        if table == "hurdat_tracks":
            conn.execute("""
                ALTER TABLE stage_hurdat_tracks
                DROP COLUMN track_id
            """)

        buffer = StringIO()
        df.to_csv(buffer, index=False, na_rep="")
        cols = ", ".join(columns)
        with conn.cursor() as cur:
            with cur.copy(f"""
                COPY stage_{table} ({cols})
                FROM STDIN (FORMAT csv, HEADER true)
            """) as copy:
                copy.write(buffer.getvalue().encode("utf-8"))

    print(f"Staged {len(storms):,} storms and {len(tracks):,} tracks")


def validate(conn):
    checks = {
        "No storm headers": "SELECT COUNT(*) = 0 FROM stage_hurdat_storms",
        "No track points": "SELECT COUNT(*) = 0 FROM stage_hurdat_tracks",
        "Duplicate storm IDs": """SELECT COUNT(*) <> COUNT(DISTINCT storm_id)
                                  FROM stage_hurdat_storms""",
        "Duplicate track keys": """SELECT COUNT(*) <> COUNT(DISTINCT
                                  (storm_id, observed_at, record_identifier))
                                  FROM stage_hurdat_tracks""",
        "Missing parent storms": """SELECT EXISTS (
              SELECT 1 FROM stage_hurdat_tracks t
              LEFT JOIN stage_hurdat_storms s USING (storm_id)
              WHERE s.storm_id IS NULL)""",
        "Incorrect storm track counts": """SELECT EXISTS (
              SELECT 1 FROM stage_hurdat_storms s
              LEFT JOIN (
                  SELECT storm_id, COUNT(*) AS n
                  FROM stage_hurdat_tracks GROUP BY storm_id
              ) t USING (storm_id)
              WHERE s.num_track_points <> COALESCE(t.n, 0))""",
        "Invalid track fields": """SELECT EXISTS (
              SELECT 1 FROM stage_hurdat_tracks
              WHERE observed_at IS NULL OR system_status IS NULL
                 OR lat IS NULL OR lon IS NULL
                 OR lat NOT BETWEEN -90 AND 90 OR lon NOT BETWEEN -180 AND 180
                 OR max_wind_kt < 0 OR min_pressure_mb <= 0)""",
    }
    for label, sql in checks.items():
        if conn.execute(sql).fetchone()[0]:
            raise ValueError(f"HURDAT2 validation failed: {label}")
    print("HURDAT2 staging validation passed")


def merge(conn):
    """Insert or update storm headers first, then their track observations."""
    inserted, updated = 0, 0

    # making it merge dynamically for both tables

    for target, columns, keys in [
        ("hurdat_storms", STORM_COLUMNS, ["storm_id"]),
        ("hurdat_tracks", TRACK_COLUMNS,
         ["storm_id", "observed_at", "record_identifier"]),
    ]:
        # stage is the staging table name
        stage = f"stage_{target}"
        
        # nonkeys are columns we will insert that aren't PK or FK
        nonkeys = [c for c in columns if c not in keys]

        # count where keys match in stage and full table to get number inserted
        key_check = " AND ".join(f"t.{key} = s.{key}" for key in keys)
        n_insert = conn.execute(f"""
            SELECT COUNT(*) FROM {stage} s
            WHERE NOT EXISTS (SELECT 1 FROM prancer.{target} t WHERE {key_check})
        """).fetchone()[0]

        # construct columns and keys for conflict resolution
        cols = ", ".join(columns)
        conflicts = ", ".join(keys)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in nonkeys)

        # two lists of values to compare if anything has changed and needs to be updated 
        old = ", ".join(f"{target}.{c}" for c in nonkeys)
        new = ", ".join(f"EXCLUDED.{c}" for c in nonkeys)
        result = conn.execute(f"""
            INSERT INTO prancer.{target} ({cols})
            SELECT {cols} FROM {stage} WHERE TRUE
            ON CONFLICT ({conflicts}) DO UPDATE SET {updates}
            WHERE ({old}) IS DISTINCT FROM ({new})
        """)
        inserted += n_insert
        updated += result.rowcount - n_insert
    return inserted, updated


def already_loaded(conn, filename):
    result = conn.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM prancer.ingestion_runs
            WHERE source = 'hurdat2'
              AND filename = %s
              AND status = 'success'
        )
    """, (filename,)).fetchone()

    return result[0]


def record_success(conn, filename, staged, inserted, updated):
    conn.execute("""
        INSERT INTO prancer.ingestion_runs (
            source,
            filename,
            status,
            rows_staged,
            rows_inserted,
            rows_updated
        )
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        "hurdat2",
        filename,
        "success",
        staged,
        inserted,
        updated
    ))


def refresh_hurricanes():
    # Find the latest Atlantic archive in NOAA's directory listing.
    response = requests.get(BASE_URL, timeout=30)
    response.raise_for_status()
    matches = re.findall(r'hurdat2-1851-\d{4}-[^"<>/\s]+\.txt', response.text)
    if not matches:
        raise ValueError("No Atlantic HURDAT2 archive found")
    filename = max(matches)

    print(f"Reading {filename}")

    with connect(team="prancer", autocommit=True) as conn:

        if already_loaded(conn, filename):
            print(f"Skipping {filename}: already loaded")
            return

        response = requests.get(BASE_URL + filename, timeout=120)
        response.raise_for_status()

        storms, tracks = transform_hurricanes(
            response.content.decode("utf-8-sig")
        )

        with conn.transaction():
            load_stage(conn, storms, tracks)
            validate(conn)

            inserted, updated = merge(conn)

            record_success(
                conn,
                filename,
                len(storms) + len(tracks),
                inserted,
                updated
            )

    print(f"Finished: {inserted:,} inserted, {updated:,} updated")

if __name__ == "__main__":
    refresh_hurricanes()
