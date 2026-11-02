# [Project name] · [team, e.g. dasher]

> **Starter repository for the 36-614 project.** Every requirement is in the
> [project brief](https://stat.cmu.edu/~sgallagh/courses/mads-fall-2026/computing-36614/final-project-framework.html); these files only show where each piece goes, with short
> examples from the shared course weather data. Replace the examples, and delete these
> notes before you tag `handoff`.

## What this system is for

*Two or three sentences: who the client is, what decision the system supports, and what
it does not cover.*

## Start here

*The first commands a receiving team should run, in order, with what each one should
print. Example:*

1. `python3.13 -m venv .venv` and `.venv/bin/python -m pip install -r requirements.txt`,
   then select the `.venv` interpreter in VS Code. The install should end with
   "Successfully installed …".
2. `export PGUSER="andrewid@andrew.cmu.edu"` and `python src/course_db.py`. It should
   print "Connected to mads_f26 as …".
3. `python src/refresh.py --team dasher --start 2025-09-01 --end 2025-10-01 --dry-run`.
   It should report how many rows it would insert and update, then undo everything.
4. `python src/report.py --team dasher --state PA --start 2025-09-01 --end 2025-10-01`.
   It should print a table of stations.

## What's in the handoff pack

| Piece | Where |
|---|---|
| **README:** where to start | this file |
| **Technical specification:** overview and scope, process-flow and ER diagrams, sources, every table, program, and query, design decisions, known issues | `docs/technical-spec.md` |
| **Runbook:** connect, refresh, check, recover, and use and maintain the reports | `docs/runbook.md` |
| **The code:** schema, refresh, client queries and their tests, Python command, report, Python packages | `sql/schema.sql`, `src/refresh.py`, `sql/queries/`, `sql/tests/`, `src/report.py`, `reports/report.qmd`, `requirements.txt` |
| **AI log** | `ai/AI-LOG.md` |
| **Knowledge transfer plan:** topics, required or not, priority, complexity, prerequisites, estimated times | `docs/kt-log.md` |

`docs/kt-log.md` is the knowledge transfer log: plan it by the `handoff` tag on November
20, and fill it in during the knowledge transfer on November 23.

`src/course_db.py` connects to the course server with your CMU sign-in; don't edit it.
`receiver/` stays empty until the handoff; the receiving team works there.

## Rules for this repository

- **No credentials, ever:** no passwords, tokens, or connection strings with secrets,
  including in old commits. `course_db.py` signs in with your CMU account, so you never
  need one.
- Raw downloads go in `data/raw/`, which Git ignores. The refresh step must be able to
  fetch them again.
- **Work as your team.** Before you create anything, switch to your team role. Tables
  created without it belong to you personally and won't transfer at the handoff.

  ```sql
  SET ROLE prancer_write;
  SET search_path = prancer, course, public;
  ```

  In Python, `course_db.connect(team="prancer")` does both.
- **Name everything in lowercase snake_case**, such as `begin_yearmonth` or
  `ev_level2_evse_num`. PostgreSQL lowercases names that aren't in double quotes, so a
  column created as `BEGIN_YEARMONTH` or `EV Level2 EVSE Num` can only be queried with
  the double quotes, every time. `df.to_sql()` keeps a file's headers exactly as they
  are, so clean them before loading:

  ```python
  df.columns = df.columns.str.lower().str.replace(r"[^a-z0-9]+", "_", regex=True)
  ```
