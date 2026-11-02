"""Connect to the 36-614 course database from Python with your CMU sign-in.

There is no course database password. Python asks Microsoft for a short-lived token
using your CMU (Entra) sign-in and uses it as the password.

One-time setup: build the course Python environment from requirements.txt (setup
primer, step 5), which installs psycopg and azure-identity:

    python -m pip install -r requirements.txt

and tell the helper who you are, for example in your shell profile:

    export PGUSER="andrewid@andrew.cmu.edu"

Signing in: if you install the Azure CLI and run `az login --allow-no-subscriptions`
once, connections then work without prompting. Otherwise a browser window opens for
your CMU sign-in.

Usage:

    from course_db import connect

    with connect() as conn:                  # shared course data
        print(conn.execute("SELECT count(*) FROM stations").fetchone())

    with connect(team="prancer") as conn:   # build as your team
        conn.execute("CREATE TABLE ...")

Check your setup by running this file: python course_db.py
"""

from __future__ import annotations

import os

import psycopg
from psycopg import sql

HOST = "mads-pg-skg.postgres.database.azure.com"
DATABASE = "mads_f26"
TEAMS = frozenset(
    ["dasher", "dancer", "prancer", "vixen", "comet", "cupid", "donner", "blitzen"]
)

# The Microsoft Entra resource for Azure Database for PostgreSQL. A token lasts 5 to 60
# minutes, so a fresh one is requested for every connection; it is never stored.
TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

_credential = None


def _access_token() -> str:
    global _credential
    if _credential is None:
        from azure.identity import DefaultAzureCredential

        # Uses `az login` if available; otherwise opens a browser for CMU sign-in.
        _credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
    return _credential.get_token(TOKEN_SCOPE).token


def connect(team: str | None = None, **settings) -> psycopg.Connection:
    """Open a connection to mads_f26 as yourself.

    With team="prancer" (for example), the connection builds as that team: it runs
    SET ROLE prancer_write, so new tables belong to the team and survive the handoff,
    and it searches the team's schema before the shared course data.
    """
    user = os.environ.get("PGUSER")
    if not user:
        raise RuntimeError(
            'Set PGUSER to your Andrew address, e.g. export PGUSER="andrewid@andrew.cmu.edu"'
        )
    if team is not None and team not in TEAMS:
        raise ValueError(f"Unknown team {team!r}; expected one of {sorted(TEAMS)}")

    params = {"host": HOST, "dbname": DATABASE, "user": user, "sslmode": "require"}
    params.update(settings)
    conn = psycopg.connect(password=_access_token(), **params)

    if team is not None:
        try:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(f"{team}_write")))
            conn.execute(
                sql.SQL("SET search_path = {}, course, public").format(sql.Identifier(team))
            )
            conn.commit()
        except psycopg.Error:
            conn.close()
            raise
    return conn


if __name__ == "__main__":
    with connect() as conn:
        database, signed_in_as, acting_as, now = conn.execute(
            "SELECT current_database(), session_user, current_user, now()"
        ).fetchone()
    print(f"Connected to {database} as {signed_in_as} (acting as {acting_as}) at {now}")
