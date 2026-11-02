"""Report: a client query that takes parameters.

    python src/report.py --team dasher --state PA --start 2025-09-01 --end 2025-10-01

The example counts rainy days by station on the shared course data. Replace the query
and the options with one of your client questions. Send every value to the database as
a parameter, as below: never build SQL with f-strings or string concatenation.
"""

from __future__ import annotations

import argparse
from datetime import date

from course_db import connect

QUERY = """
    SELECT s.station_id, s.name, count(*) AS rainy_days
    FROM course.observations AS o
    JOIN course.stations AS s USING (station_id)
    WHERE s.state = %(state)s
      AND o.date >= %(start)s
      AND o.date <  %(end)s
      AND o.precip > 0
    GROUP BY s.station_id, s.name
    ORDER BY rainy_days DESC, s.name
    LIMIT %(limit)s
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Rainy days by station (example).")
    parser.add_argument("--team", help="your team, e.g. dasher")
    parser.add_argument("--state", required=True, help="two-letter state code, e.g. PA")
    parser.add_argument("--start", type=date.fromisoformat, required=True,
                        help="first date, YYYY-MM-DD")
    parser.add_argument("--end", type=date.fromisoformat, required=True,
                        help="day after the last date, YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=25, help="rows to show (default 25)")
    args = parser.parse_args()

    params = {"state": args.state.upper(), "start": args.start, "end": args.end,
              "limit": args.limit}
    with connect(team=args.team) as conn:
        rows = conn.execute(QUERY, params).fetchall()

    if not rows:
        print("No stations matched.")
        return
    print(f"{'station_id':<12}  {'name':<32}  rainy_days")
    for station_id, name, rainy_days in rows:
        print(f"{station_id:<12}  {name:<32}  {rainy_days:>10}")


if __name__ == "__main__":
    main()
