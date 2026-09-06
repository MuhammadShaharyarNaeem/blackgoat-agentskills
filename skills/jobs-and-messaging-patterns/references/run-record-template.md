# Run record template

The shape referenced by *Run Records for Scheduled Jobs* in `../SKILL.md`. Copy it;
replace every `<...>`.

## Why a record and not a log line

The question a run record answers is asked by **the next run**, not by a human: *did the
previous run finish, how far did it get, and is there work it left behind?* A log stream
answers that only if someone is watching at the right moment with the right query. A row
answers it to a `SELECT`.

That is also what makes a job restartable. A job that knows its last successful watermark
resumes; a job that does not either re-processes everything (safe only if every handler
is idempotent — see the contract) or skips the gap silently.

## Fields

| Field | Type | Purpose |
|---|---|---|
| `job_name` | text | Stable identifier — the scheduler's name for it, not a description |
| `run_id` | id | One per attempt, including retried attempts |
| `correlation_id` | text | Propagated into every log line and every message this run publishes (`{PLUGIN_ROOT}/observability-and-diagnosis/SKILL.md`) |
| `started_at` | timestamp | Written **at start**, not at finish — a row with no `finished_at` is how a crashed run announces itself |
| `finished_at` | timestamp, nullable | `NULL` while running or after a crash |
| `status` | enum | `running`, `succeeded`, `failed`, `partial` |
| `items_processed` | int | Count of items the run actually acted on |
| `items_failed` | int | Count that errored; non-zero with `status: succeeded` is a contradiction worth a constraint |
| `watermark` | text, nullable | Where to resume — the last id, cursor, or timestamp consumed |
| `error` | text, nullable | The failure's message, for `failed` and `partial` |
| `trigger` | enum | `schedule`, `manual`, `retry` — a manual re-run and a scheduled one produce different expectations |

## Rules

- **Insert the row at start, update it at finish.** A record written only on success cannot
  distinguish "never ran" from "died halfway", and those have opposite remediations.
- **`items_processed` counts effects, not iterations.** A run that skipped 10,000 already
  processed items and applied 3 reports 3, and says so — an `items_skipped` column where
  the distinction matters operationally.
- **Zero is a value.** A nightly run that legitimately found nothing to do writes a row
  with `items_processed: 0` and `status: succeeded`. Writing no row makes "found nothing"
  and "did not run" indistinguishable, which is the failure this table exists to prevent.
- **A crash leaves `status: running` behind.** Decide, at planning time, whether the next
  run treats a stale `running` row as "another instance is live, exit" or "the previous
  instance died, take over" — and what age separates the two. Both are defensible; an
  unstated choice is not.
- Retention: keep enough runs to answer *when did this last work?* Prune by age, and prune
  with the job's own scheduled cadence in mind.

## Template

```
- Job name: <scheduler's identifier>
- Run id: <id>
- Correlation id: <id propagated into logs and published messages>
- Trigger: <schedule | manual | retry>
- Started at: <ISO-8601 timestamp>
- Finished at: <ISO-8601 timestamp, or empty while running>
- Status: <running | succeeded | failed | partial>
- Items processed: <n>
- Items failed: <n>
- Watermark: <last id / cursor / timestamp consumed, or empty>
- Error: <message, for failed and partial>
```

The block above is the *shape*; the storage is a table in the project's own datastore. A
markdown file is not a run record — the next run cannot query it.
