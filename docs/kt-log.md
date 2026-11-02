# Knowledge transfer log: [system name]

> **What goes here:** a checklist of everything the receiving team needs to learn, and a
> record of when each topic was transferred. The builders plan it by the `handoff` tag
> on November 20: mark which topics are required, set their priority, complexity, and
> prerequisites, and estimate the time for each. Fill in the status, actual time, and
> date during the knowledge transfer on November 23 and the follow-up questions after
> it. Both teams sign off when the transfer is complete. Add rows for your own sources,
> tables, and reports; delete rows that don't apply.

| | |
|---|---|
| **Builders** | [team, names] |
| **Receivers** | [team, names] |
| **System** | [system name] |
| **Technical specification** | [`docs/technical-spec.md`](technical-spec.md) |
| **Last updated, and by whom** | |

## Sign-offs

| | Name | Date |
|---|---|---|
| Builders: knowledge transferred | | |
| Receivers: knowledge received, taking ownership | | |

## Topics

**Required:** Y or N. **Status:** complete, in progress, or not started. **Priority**
and **complexity:** high, moderate, or low. **Prerequisite:** the topic that has to come
first. **Times** are in minutes.

| Topic | Required | Status | Priority | Complexity | Prerequisite | Est. time | Actual time | KT date |
|---|---|---|---|---|---|---:|---:|---|
| **A. System overview** | | | | | | | | |
| A1. The client, the decision, and what the system is for *(example)* | Y | complete | high | low | none | 5 | 6 | Nov 23 |
| A2. Scope: what's in, what's out, and why | | | | | A1 | | | |
| A3. Process flow: sources to staging to trusted tables to reports | | | | | A1 | | | |
| **B. Sources** | | | | | | | | |
| B1. [Source name]: where it comes from, access, update schedule | | | | | A3 | | | |
| B2. [Source name] | | | | | A3 | | | |
| **C. Schema** | | | | | | | | |
| C1. ER diagram and relationships | | | | | A3 | | | |
| C2. [Table]: row unit, keys, constraints | | | | | C1 | | | |
| C3. Spatial join keys and enrichment joins | | | | | C1 | | | |
| **D. Pipeline** | | | | | | | | |
| D1. Connecting: CMU sign-in, team role, `course_db.py` | | | | | none | | | |
| D2. The refresh command, for each source | | | | | D1, B | | | |
| D3. Staging and validation checks | | | | | D2 | | | |
| D4. Merge and rerun safety | | | | | D3 | | | |
| D5. Run log (`ingestion_runs`) | | | | | D2 | | | |
| **E. Queries and reports** | | | | | | | | |
| E1. Client query library and its tests | | | | | C | | | |
| E2. The Python report command | | | | | D1 | | | |
| E3. [Part II visualization]: how to regenerate and maintain it | | | | | E1 | | | |
| **F. What if?** | | | | | | | | |
| F1. A refresh fails partway | | | | | D | | | |
| F2. A source is down or changes its format | | | | | B, D | | | |
| F3. Validation rejects rows | | | | | D3 | | | |
| F4. The source revises data already loaded | | | | | D4 | | | |
| **G. Quality checks** | | | | | | | | |
| G1. Run the tests in `sql/tests/` | | | | | E1 | | | |
| G2. Check row counts and date coverage after a refresh | | | | | D2 | | | |
| G3. Reproduce one documented result | | | | | E1 | | | |

## Questions and open items

> Every question the receivers asked, its answer, and anything left unresolved.

| Date | Question or open item | Answer or status |
|---|---|---|
| | | |
