"""Refresh: pull new data for a chosen source and merge it safely.

Each source updates on its own schedule:
  - ghcn   (daily):   python src/refresh.py --team prancer --source ghcn --start 2025-09-01 --end 2025-10-01
  - nws    (hourly):  python src/refresh.py --team prancer --source nws
  - storms (monthly): python src/refresh.py --team prancer --source storms --start 2026-01-01 --end 2026-12-31
  - hurdat (season):  python src/refresh.py --team prancer --source hurdat
  - census (annual):  python src/refresh.py --team prancer --source census --dry-run
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urljoin

import psycopg
import requests
from course_db import connect

HEADERS = {
    "User-Agent": "36-614 project (ahou@andrew.cmu.edu)",
    "Accept": "application/geo+json",
}
NWS_STATIONS = ["KPIT", "KMIA", "KHOU", "KDFW", "KORD"]
STATE_ABBR = {
    "01": "AL",
    "02": "AK",
    "04": "AZ",
    "05": "AR",
    "06": "CA",
    "08": "CO",
    "09": "CT",
    "10": "DE",
    "11": "DC",
    "12": "FL",
    "13": "GA",
    "15": "HI",
    "16": "ID",
    "17": "IL",
    "18": "IN",
    "19": "IA",
    "20": "KS",
    "21": "KY",
    "22": "LA",
    "23": "ME",
    "24": "MD",
    "25": "MA",
    "26": "MI",
    "27": "MN",
    "28": "MS",
    "29": "MO",
    "30": "MT",
    "31": "NE",
    "32": "NV",
    "33": "NH",
    "34": "NJ",
    "35": "NM",
    "36": "NY",
    "37": "NC",
    "38": "ND",
    "39": "OH",
    "40": "OK",
    "41": "OR",
    "42": "PA",
    "44": "RI",
    "45": "SC",
    "46": "SD",
    "47": "TN",
    "48": "TX",
    "49": "UT",
    "50": "VT",
    "51": "VA",
    "53": "WA",
    "54": "WV",
    "55": "WI",
    "56": "WY",
}
DAMAGE_MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def log_run(
    conn: psycopg.Connection,
    source_label: str,
    staged: int,
    inserted: int,
    updated: int,
) -> None:
    """Record each completed refresh run in ingestion_runs."""
    conn.execute(
        """
        INSERT INTO ingestion_runs (source, rows_staged, rows_inserted, rows_updated)
        VALUES (%s, %s, %s, %s)
        """,
        (source_label, staged, inserted, updated),
    )


def run_checks(conn: psycopg.Connection, checks: dict[str, str]) -> None:
    """Run validation queries on the staging table; abort and roll back if any fail."""
    problems = []
    for name, query in checks.items():
        (count,) = conn.execute(query).fetchone()
        if count:
            problems.append(f"{name}: {count}")
    if problems:
        raise SystemExit(
            "Validation failed; nothing was loaded:\n  "
            + "\n  ".join(problems)
        )


# 1. GHCN-DAILY (Daily schedule)
def refresh_ghcn(
    conn: psycopg.Connection, start: date, end: date
) -> tuple[int, int, int]:
    rows = conn.execute(
        """
        SELECT station_id, date, tmax, tmin, precip
        FROM course.observations
        WHERE date >= %s AND date < %s
        """,
        (start, end),
    ).fetchall()

    conn.execute("DROP TABLE IF EXISTS pg_temp.stage_observations")
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

    run_checks(
        conn,
        {
            "duplicate (station_id, date) in stage": """
            SELECT count(*) FROM (
              SELECT station_id, date FROM stage_observations GROUP BY station_id, date HAVING count(*) > 1
            ) t""",
            "negative precipitation": "SELECT count(*) FROM stage_observations WHERE precip < 0",
            "tmax below tmin": "SELECT count(*) FROM stage_observations WHERE tmax < tmin",
            "unknown station_id": """
            SELECT count(*) FROM stage_observations s
            WHERE NOT EXISTS (SELECT 1 FROM course.stations c WHERE c.station_id = s.station_id)""",
        },
    )

    conn.execute(
        """
        INSERT INTO stations (station_id, name, state, lat, lon, elevation)
        SELECT c.station_id, c.name, c.state, c.lat, c.lon, c.elevation
        FROM course.stations AS c
        WHERE c.station_id IN (SELECT station_id FROM stage_observations)
        ON CONFLICT (station_id) DO NOTHING
        """
    )
    conn.execute(
        """
        UPDATE stations AS s
        SET county_fips = (
          SELECT c.county_fips
          FROM course.counties AS c
          WHERE c.state = s.state
          ORDER BY ((c.lat - s.lat) * 69.0)^2 + ((c.lon - s.lon) * 69.0 * cos(radians(s.lat)))^2
          LIMIT 1
        )
        WHERE s.county_fips IS NULL AND s.state IS NOT NULL
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
    return len(rows), inserted, changed - inserted


# 2. NWS API OBSERVATIONS (Live / Hourly schedule)
def refresh_nws(conn: psycopg.Connection) -> tuple[int, int, int]:
    rows = []
    for stn in NWS_STATIONS:
        resp = requests.get(
            f"https://api.weather.gov/stations/{stn}/observations",
            params={"limit": 500},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        for feat in resp.json().get("features", []):
            p = feat["properties"]
            coords = (feat.get("geometry") or {}).get("coordinates") or []
            lon, lat = coords if len(coords) >= 2 else (None, None)
            rows.append(
                (
                    p["stationId"],
                    p["timestamp"],
                    lat,
                    lon,
                    p["temperature"]["value"],
                    p["dewpoint"]["value"],
                    p["windSpeed"]["value"],
                    p["windGust"]["value"],
                    p["barometricPressure"]["value"],
                    p["relativeHumidity"]["value"],
                    p["textDescription"],
                )
            )

    conn.execute("DROP TABLE IF EXISTS pg_temp.stage_nws")
    conn.execute(
        "CREATE TEMP TABLE stage_nws (LIKE nws_observations) ON COMMIT DROP"
    )
    with conn.cursor() as cur:
        with cur.copy("COPY stage_nws FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)

    run_checks(
        conn,
        {
            "duplicate (station_id, observed_at)": """
            SELECT count(*) FROM (
              SELECT station_id, observed_at FROM stage_nws GROUP BY station_id, observed_at HAVING count(*) > 1
            ) t""",
            "negative wind speed": "SELECT count(*) FROM stage_nws WHERE wind_speed_kmh < 0",
        },
    )

    (before,) = conn.execute(
        "SELECT count(*) FROM nws_observations"
    ).fetchone()
    changed = conn.execute(
        """
        INSERT INTO nws_observations
        SELECT * FROM stage_nws
        ON CONFLICT (station_id, observed_at) DO UPDATE SET
          temperature_c = EXCLUDED.temperature_c,
          dewpoint_c = EXCLUDED.dewpoint_c,
          wind_speed_kmh = EXCLUDED.wind_speed_kmh,
          wind_gust_kmh = EXCLUDED.wind_gust_kmh,
          barometric_pressure_pa = EXCLUDED.barometric_pressure_pa,
          relative_humidity_pct = EXCLUDED.relative_humidity_pct,
          text_description = EXCLUDED.text_description
        WHERE (nws_observations.temperature_c, nws_observations.wind_speed_kmh, nws_observations.barometric_pressure_pa)
              IS DISTINCT FROM (EXCLUDED.temperature_c, EXCLUDED.wind_speed_kmh, EXCLUDED.barometric_pressure_pa)
        RETURNING 1
        """
    ).rowcount
    (after,) = conn.execute(
        "SELECT count(*) FROM nws_observations"
    ).fetchone()
    inserted = after - before
    return len(rows), inserted, changed - inserted


# 3. NOAA STORM EVENTS (Monthly schedule)
def parse_damage(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    s = val.strip().upper()
    if s[-1] in DAMAGE_MULT:
        num = s[:-1].strip()
        return float(num) * DAMAGE_MULT[s[-1]] if num else 0.0
    try:
        return float(s)
    except ValueError:
        return None


def refresh_storms(
    conn: psycopg.Connection, start: date, end: date
) -> tuple[int, int, int]:
    base_url = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
    raw_dir = Path("data/raw/storm_events")
    raw_dir.mkdir(parents=True, exist_ok=True)

    idx_resp = requests.get(base_url, headers=HEADERS, timeout=30)
    idx_resp.raise_for_status()
    index_html = idx_resp.text

    valid_fips = {
        fips.strip()
        for (fips,) in conn.execute(
            "SELECT county_fips FROM course.counties"
        ).fetchall()
    }
    rows = []

    for yr in range(start.year, end.year + 1):
        matches = re.findall(
            rf'href="(StormEvents_details-ftp_v1\.0_d{yr}_c\d+\.csv\.gz)"',
            index_html,
        )
        if matches:
            fname = sorted(matches)[-1]
            fpath = raw_dir / fname
            if not fpath.exists():
                resp = requests.get(
                    base_url + fname, headers=HEADERS, timeout=120
                )
                resp.raise_for_status()
                fpath.write_bytes(resp.content)
        else:
            # Fall back to any already-downloaded file for that year in data/raw/storm_events/
            cached = sorted(
                raw_dir.glob(f"StormEvents_details-ftp_v1.0_d{yr}_c*.csv.gz")
            )
            if not cached:
                print(f"Note: no Storm Events file found for {yr}.")
                continue
            fpath = cached[-1]

        with gzip.open(
            fpath, "rt", encoding="utf-8", errors="replace", newline=""
        ) as f:
            for r in csv.DictReader(f):
                st_fp = (r.get("STATE_FIPS") or "").strip().zfill(2)
                if st_fp not in STATE_ABBR:
                    continue
                cz_type = (r.get("CZ_TYPE") or "").strip()
                if cz_type not in ("C", "Z", "M"):
                    continue
                cz_fp = (r.get("CZ_FIPS") or "").strip().zfill(3)

                begin_str = (r.get("BEGIN_DATE_TIME") or "").strip()
                if not begin_str:
                    continue
                begin_ts = datetime.strptime(
                    begin_str, "%d-%b-%y %H:%M:%S"
                ).replace(tzinfo=UTC)
                if not (start <= begin_ts.date() < end):
                    continue

                end_str = (r.get("END_DATE_TIME") or "").strip()
                end_ts = (
                    datetime.strptime(end_str, "%d-%b-%y %H:%M:%S").replace(
                        tzinfo=UTC
                    )
                    if end_str
                    else None
                )

                lat = (
                    float(r["BEGIN_LAT"])
                    if (r.get("BEGIN_LAT") or "").strip()
                    else None
                )
                lon = (
                    float(r["BEGIN_LON"])
                    if (r.get("BEGIN_LON") or "").strip()
                    else None
                )
                end_lat = (
                    float(r["END_LAT"])
                    if (r.get("END_LAT") or "").strip()
                    else None
                )
                end_lon = (
                    float(r["END_LON"])
                    if (r.get("END_LON") or "").strip()
                    else None
                )
                if lat is not None and not (-90 <= lat <= 90):
                    lat = None
                if lon is not None and not (-180 <= lon <= 180):
                    lon = None
                if end_lat is not None and not (-90 <= end_lat <= 90):
                    end_lat = None
                if end_lon is not None and not (-180 <= end_lon <= 180):
                    end_lon = None

                fips = (
                    f"{st_fp}{cz_fp}"
                    if (cz_type == "C" and f"{st_fp}{cz_fp}" in valid_fips)
                    else None
                )
                fips_src = "direct" if fips else "unmatched"

                rows.append(
                    (
                        int(r["EVENT_ID"]),
                        int(r["EPISODE_ID"])
                        if (r.get("EPISODE_ID") or "").strip()
                        else None,
                        st_fp,
                        STATE_ABBR[st_fp],
                        (r.get("STATE") or "").strip(),
                        cz_type,
                        cz_fp,
                        fips,
                        (r.get("EVENT_TYPE") or "").strip(),
                        begin_ts,
                        end_ts,
                        max(0, int(r.get("INJURIES_DIRECT") or 0)),
                        max(0, int(r.get("INJURIES_INDIRECT") or 0)),
                        max(0, int(r.get("DEATHS_DIRECT") or 0)),
                        max(0, int(r.get("DEATHS_INDIRECT") or 0)),
                        parse_damage(r.get("DAMAGE_PROPERTY")),
                        parse_damage(r.get("DAMAGE_CROPS")),
                        float(r["MAGNITUDE"])
                        if (r.get("MAGNITUDE") or "").strip()
                        else None,
                        (r.get("MAGNITUDE_TYPE") or "").strip() or None,
                        lat,
                        lon,
                        end_lat,
                        end_lon,
                        fips_src,
                    )
                )

    conn.execute("DROP TABLE IF EXISTS pg_temp.stage_storms")
    conn.execute(
        "CREATE TEMP TABLE stage_storms (LIKE storm_events INCLUDING DEFAULTS) ON COMMIT DROP"
    )
    with conn.cursor() as cur:
        with cur.copy("COPY stage_storms FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)

    run_checks(
        conn,
        {
            "duplicate event_id in stage": """
            SELECT count(*) FROM (
              SELECT event_id FROM stage_storms GROUP BY event_id HAVING count(*) > 1
            ) t""",
            "negative property damage": "SELECT count(*) FROM stage_storms WHERE damage_property_usd < 0",
            "negative deaths": "SELECT count(*) FROM stage_storms WHERE deaths_direct < 0 OR deaths_indirect < 0",
        },
    )

    (before,) = conn.execute("SELECT count(*) FROM storm_events").fetchone()
    changed = conn.execute(
        """
        INSERT INTO storm_events
        SELECT * FROM stage_storms
        ON CONFLICT (event_id) DO UPDATE SET
          damage_property_usd = EXCLUDED.damage_property_usd,
          damage_crops_usd = EXCLUDED.damage_crops_usd,
          deaths_direct = EXCLUDED.deaths_direct,
          deaths_indirect = EXCLUDED.deaths_indirect,
          county_fips = COALESCE(EXCLUDED.county_fips, storm_events.county_fips)
        WHERE (storm_events.damage_property_usd, storm_events.damage_crops_usd, storm_events.deaths_direct)
              IS DISTINCT FROM (EXCLUDED.damage_property_usd, EXCLUDED.damage_crops_usd, EXCLUDED.deaths_direct)
        RETURNING 1
        """
    ).rowcount
    (after,) = conn.execute("SELECT count(*) FROM storm_events").fetchone()
    inserted = after - before
    return len(rows), inserted, changed - inserted


# 4. HURDAT2 ATLANTIC BEST TRACKS (Seasonal schedule)
def refresh_hurdat(
    conn: psycopg.Connection, min_year: int = 1980
) -> tuple[int, int, int]:
    index_url = "https://www.nhc.noaa.gov/data/hurdat/"
    idx_resp = requests.get(index_url, headers=HEADERS, timeout=30)
    idx_resp.raise_for_status()
    matches = re.findall(
        r'href="([^"]*hurdat2-1851-[^"]+\.txt)"',
        idx_resp.text,
        flags=re.IGNORECASE,
    )
    file_url = urljoin(index_url, sorted(matches)[-1])
    resp = requests.get(file_url, headers=HEADERS, timeout=60)
    resp.raise_for_status()

    storms, tracks = [], []
    cur_id, expected, seen, keep = None, 0, 0, False
    for line in resp.text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4:
            storm_id, name, n_s, _ = parts
            if storm_id[:2] in ("AL", "EP", "CP"):
                if cur_id is not None and seen != expected:
                    raise SystemExit(
                        f"HURDAT2 integrity error on {cur_id}: expected {expected} pts, saw {seen}"
                    )
                cur_id, expected, seen = storm_id, int(n_s), 0
                yr = int(cur_id[4:8])
                keep = yr >= min_year
                if keep:
                    storms.append(
                        (
                            cur_id,
                            name,
                            cur_id[:2],
                            int(cur_id[2:4]),
                            yr,
                            expected,
                        )
                    )
        elif len(parts) in (20, 21):
            seen += 1
            if not keep:
                continue
            ymd, hm, rec_id, status, lat_s, lon_s, wind_s, pres_s = parts[:8]
            rec_id = rec_id or "R"
            dt = datetime.strptime(ymd + hm.zfill(4), "%Y%m%d%H%M").replace(
                tzinfo=UTC
            )
            lat = float(lat_s[:-1]) * (-1 if lat_s.endswith("S") else 1)
            lon = float(lon_s[:-1]) * (-1 if lon_s.endswith("W") else 1)
            wind = int(wind_s) if int(wind_s) >= 0 else None
            pres = int(pres_s) if int(pres_s) > 0 else None
            tracks.append((cur_id, dt, rec_id, status, lat, lon, wind, pres))

    conn.execute("DROP TABLE IF EXISTS pg_temp.stage_hurdat_tracks")
    conn.execute(
        """
        CREATE TEMP TABLE stage_hurdat_tracks (
          storm_id TEXT, observed_at TIMESTAMPTZ, record_identifier CHAR(1),
          system_status TEXT, lat DOUBLE PRECISION, lon DOUBLE PRECISION,
          max_wind_kt INTEGER, min_pressure_mb INTEGER
        ) ON COMMIT DROP
        """
    )
    with conn.cursor() as cur:
        with cur.copy("COPY stage_hurdat_tracks FROM STDIN") as copy:
            for row in tracks:
                copy.write_row(row)

    run_checks(
        conn,
        {
            "duplicate track fix": """
            SELECT count(*) FROM (
              SELECT storm_id, observed_at, record_identifier FROM stage_hurdat_tracks
              GROUP BY 1, 2, 3 HAVING count(*) > 1
            ) t""",
            "invalid latitude": "SELECT count(*) FROM stage_hurdat_tracks WHERE lat NOT BETWEEN -90 AND 90",
            "invalid longitude": "SELECT count(*) FROM stage_hurdat_tracks WHERE lon NOT BETWEEN -180 AND 180",
        },
    )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO hurdat_storms (storm_id, storm_name, basin, cyclone_number, season_year, num_track_points)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (storm_id) DO UPDATE SET
              storm_name = EXCLUDED.storm_name,
              num_track_points = EXCLUDED.num_track_points
            """,
            storms,
        )

        (before,) = conn.execute(
            "SELECT count(*) FROM hurdat_tracks"
        ).fetchone()
    changed = conn.execute(
        """
        INSERT INTO hurdat_tracks (storm_id, observed_at, record_identifier, system_status, lat, lon, max_wind_kt, min_pressure_mb)
        SELECT storm_id, observed_at, record_identifier, system_status, lat, lon, max_wind_kt, min_pressure_mb
        FROM stage_hurdat_tracks
        ON CONFLICT (storm_id, observed_at, record_identifier) DO UPDATE SET
          system_status = EXCLUDED.system_status,
          lat = EXCLUDED.lat,
          lon = EXCLUDED.lon,
          max_wind_kt = EXCLUDED.max_wind_kt,
          min_pressure_mb = EXCLUDED.min_pressure_mb
        WHERE (hurdat_tracks.max_wind_kt, hurdat_tracks.min_pressure_mb, hurdat_tracks.lat, hurdat_tracks.lon)
              IS DISTINCT FROM (EXCLUDED.max_wind_kt, EXCLUDED.min_pressure_mb, EXCLUDED.lat, EXCLUDED.lon)
        RETURNING 1
        """
    ).rowcount
    (after,) = conn.execute("SELECT count(*) FROM hurdat_tracks").fetchone()
    inserted = after - before
    return len(tracks), inserted, changed - inserted


# 5. CENSUS ACS 5-YEAR DEMOGRAPHICS (Annual schedule)
def refresh_census(
    conn: psycopg.Connection, acs_year: int = 2024
) -> tuple[int, int, int]:
    api_key = os.environ.get("CENSUS_API_KEY")
    if not api_key:
        raise SystemExit("Missing CENSUS_API_KEY environment variable.")
    resp = requests.get(
        f"https://api.census.gov/data/{acs_year}/acs/acs5",
        params={
            "get": "NAME,B01003_001E,B19013_001E,B25077_001E,B25001_001E",
            "for": "county:*",
            "key": api_key,
        },
        timeout=60,
    )
    resp.raise_for_status()
    valid_fips = {
        fips.strip()
        for (fips,) in conn.execute(
            "SELECT county_fips FROM course.counties"
        ).fetchall()
    }

    clean = lambda v: (
        None if v is None or v == "" or float(v) < 0 else float(v)
    )
    rows = []
    for name, pop, inc, home, units, st, co in resp.json()[1:]:
        fips = f"{st.zfill(2)}{co.zfill(3)}"
        if fips not in valid_fips:
            continue
        pv, uv = clean(pop), clean(units)
        rows.append(
            (
                fips,
                name,
                acs_year,
                int(pv) if pv is not None else None,
                clean(inc),
                clean(home),
                int(uv) if uv is not None else None,
            )
        )

    conn.execute("DROP TABLE IF EXISTS pg_temp.stage_census")
    conn.execute(
        "CREATE TEMP TABLE stage_census (LIKE county_demographics) ON COMMIT DROP"
    )
    with conn.cursor() as cur:
        with cur.copy("COPY stage_census FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)

    run_checks(
        conn,
        {
            "negative population": "SELECT count(*) FROM stage_census WHERE population < 0",
            "negative median income": "SELECT count(*) FROM stage_census WHERE median_income < 0",
        },
    )

    (before,) = conn.execute(
        "SELECT count(*) FROM county_demographics"
    ).fetchone()
    changed = conn.execute(
        """
        INSERT INTO county_demographics
        SELECT * FROM stage_census
        ON CONFLICT (county_fips) DO UPDATE SET
          county_name = EXCLUDED.county_name,
          acs_year = EXCLUDED.acs_year,
          population = EXCLUDED.population,
          median_income = EXCLUDED.median_income,
          median_home_value = EXCLUDED.median_home_value,
          housing_units = EXCLUDED.housing_units
        WHERE (county_demographics.population, county_demographics.median_income, county_demographics.median_home_value)
              IS DISTINCT FROM (EXCLUDED.population, EXCLUDED.median_income, EXCLUDED.median_home_value)
        RETURNING 1
        """
    ).rowcount
    (after,) = conn.execute(
        "SELECT count(*) FROM county_demographics"
    ).fetchone()
    inserted = after - before
    return len(rows), inserted, changed - inserted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull new data for a source and append it safely."
    )
    parser.add_argument(
        "--team", required=True, help="your team, e.g. prancer"
    )
    parser.add_argument(
        "--source",
        default="ghcn",
        choices=["ghcn", "nws", "storms", "hurdat", "census"],
        help="which data source to refresh (each has its own schedule)",
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=date(2026, 1, 1),
        help="first date to load, YYYY-MM-DD (used by ghcn and storms)",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=date(2026, 12, 31),
        help="day after last date to load, YYYY-MM-DD (used by ghcn and storms)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="do everything, report the counts, then undo it",
    )
    args = parser.parse_args()

    with connect(team=args.team) as conn:
        with conn.transaction():
            if args.source == "ghcn":
                staged, inserted, updated = refresh_ghcn(
                    conn, args.start, args.end
                )
                label = f"ghcn ({args.start} to {args.end})"
            elif args.source == "nws":
                staged, inserted, updated = refresh_nws(conn)
                label = "nws (live observations)"
            elif args.source == "storms":
                staged, inserted, updated = refresh_storms(
                    conn, args.start, args.end
                )
                label = f"noaa_storms ({args.start} to {args.end})"
            elif args.source == "hurdat":
                staged, inserted, updated = refresh_hurdat(conn)
                label = "hurdat2 (atlantic best tracks)"
            else:
                staged, inserted, updated = refresh_census(conn)
                label = "census_acs5 (county demographics)"

            log_run(conn, label, staged, inserted, updated)
            print(
                f"[{label}] {staged} rows staged, {inserted} inserted, {updated} updated."
            )
            if args.dry_run:
                print("Dry run: undoing all changes.")
                raise psycopg.Rollback()


if __name__ == "__main__":
    main()
