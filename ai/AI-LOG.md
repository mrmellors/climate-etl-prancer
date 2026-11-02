# AI log

> **What goes here:** one table row for each substantial piece of AI-assisted work,
> newest first, and one short paragraph for each AI extension. Save prompts in
> `ai/prompts/` and link them. A check counts only if its evidence is linked; check
> numbers refer to the
> [AI verification checklist](https://stat.cmu.edu/~sgallagh/courses/mads-fall-2026/computing-36614/ai-verification-checklist.html).
> Receivers add their rows here too. Replace the example.

## Entries

| Date | Phase | Piece | Tool | Prompt | Kept, changed, or rejected | Checks and evidence |
|---|---|---|---|---|---|---|
| 2026-11-04 *(example)* | building | Merge statement in `src/refresh.py` | *assistant and version* | [prompt](prompts/2026-11-04-merge.txt) | Kept the `ON CONFLICT` merge; added `IS DISTINCT FROM` so an identical rerun doesn't rewrite every row | 4: [PostgreSQL `ON CONFLICT`](https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT); 7: `sql/tests/t02-rerun-changes-nothing.sql` |

## AI extensions

> One per phase: something AI helped you build that goes beyond what you would otherwise
> have done, verified with check 7 or deeper. One paragraph each: what it is, what it
> does for the client, and how you checked it, with links.

### Building: [name]

### Receiving: [name]

## Receivers' check of a builder entry

> Which builder row you checked, what you did to verify it yourselves, and what you found.
