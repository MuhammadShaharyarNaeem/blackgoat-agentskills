# Migration Deep Dive

Rationale, worked examples, and anti-patterns behind `database-migration-patterns/SKILL.md`. Read on demand; the contract is executable without it.

## Why Expand/Contract, Concretely

During any rollout there is a window in which **two code versions run against one database**. Every migration rule follows from that single fact:

| Moment | Old instances | New instances | Survives? |
|---|---|---|---|
| Rename column in one step | read `full_name` — now gone | read `display_name` | No — old instances 500 until the last one drains |
| Expand (add `display_name`, nullable) | read `full_name` | read `full_name` | Yes |
| Backfill `display_name` from `full_name` | unaffected | unaffected | Yes |
| Deploy dual-write, read-new | — | write both, read `display_name` | Yes |
| Contract (drop `full_name`) after no version reads it | — | read `display_name` | Yes |

The same window is why the migration deploys **before** its consuming code: if the code lands first, the new instances fail on a schema that does not exist yet, and the failure looks like an app bug rather than an ordering defect.

### Worked Rename

```
Deploy 1 (schema):   ALTER TABLE users ADD COLUMN display_name varchar(200) NULL;
Job    (backfill):   batched UPDATE users SET display_name = full_name
                     WHERE display_name IS NULL;           -- idempotent filter
Deploy 2 (code):     writes both columns, reads display_name
Deploy 3 (code):     writes display_name only
Deploy 4 (schema):   ALTER TABLE users DROP COLUMN full_name;   -- [destructive-waiver: ...]
```

Four deploys for one rename is the price of a rollout that never has a broken intermediate state. Compressing it is exactly the shortcut that produces a mid-rollout outage.

## EF Core Command Reference

```bash
# Generate the reviewable script (idempotent guards around each migration)
dotnet ef migrations script --idempotent --from <PreviousMigration> --to <TargetMigration> \
  --output .docs/<project>/implementation/evidence/migration/<name>.sql

# Inspect what the model diff actually produced before trusting it
dotnet ef migrations list
```

Never `dotnet ef database update` against production. The reviewed script is the deployable artifact; the CLI applying a model diff live is not.

### Generated-Script Hazards

Auto-generated migrations regularly contain operations the model change did not intend:

- **Silent index drop/re-create** — a changed column type takes its indexes with it.
- **Table rebuild** — some providers implement an `ALTER` as create-copy-drop-rename, which is a full table lock and a data copy.
- **Reordered operations** — the scaffolder orders by model graph, not by safety; a drop can precede the backfill that needed the column.
- **Lost precision** — a narrowed `decimal`/`varchar` scaffolds without comment and truncates on apply.
- **Default backfill on add** — adding a non-nullable column with a default rewrites every row on some engines.

This list is why the contract requires reading the script rather than diffing the model.

## Batched Backfill Shape

```sql
-- Repeat until 0 rows affected. Idempotent: the filter, not a cursor, decides the work.
UPDATE TOP (5000) users
SET    display_name = full_name
WHERE  display_name IS NULL;
```

Properties that matter: bounded batch size (predictable lock duration and log growth), a filter on the *unfinished* state (re-running from scratch is a no-op once complete), and no dependence on remembered position (an interrupted run restarts safely). Run it outside the migration transaction; a multi-hour transaction blocks vacuum/log truncation and holds locks for its whole duration.

## Per-Engine Lock Notes

Verify against the target engine's documented behavior for its exact version — these differ by major version and are a common source of "it was online in staging".

- **PostgreSQL** — `CREATE INDEX CONCURRENTLY` avoids the write lock (cannot run in a transaction; can leave an invalid index on failure, which must be dropped and retried). Adding a column with a non-volatile default is metadata-only on modern versions. `SET lock_timeout` before DDL.
- **SQL Server** — `WITH (ONLINE = ON)` for index operations on supported editions. `ALTER TABLE ... ALTER COLUMN` can be a size-of-data operation. `SET LOCK_TIMEOUT`.
- **MySQL/MariaDB** — `ALGORITHM=INPLACE, LOCK=NONE` where supported; otherwise the operation copies the table. Check per-DDL support rather than assuming.

## Anti-Patterns

| Anti-pattern | Why it fails | Instead |
|---|---|---|
| "We'll just run the down-migration" | Drops data written since the up-migration; may be un-runnable after a partial apply | Tested forward migration or verified restore |
| Migration bundled with its consuming code | No safe intermediate state; app rollback leaves a mismatched schema | Two-step deploy, schema first |
| Single `UPDATE` backfill on a large table | Long lock, log/WAL blowup, no resume point | Batched, idempotent, resumable job |
| Reviewing the C#/model diff instead of the SQL | The scaffolder's extra operations are invisible in the model diff | Read the generated script |
| Testing the migration on an empty dev database | Timing, locks and data-shape failures only appear with real volume | Apply to a copy of prod-shaped data |
| Adding `NOT NULL` to a populated column in one step | Fails outright, or rewrites every row under lock | Add nullable → backfill → add constraint |
| Silent destructive change "because the column is unused" | "Unused" is a scope-bounded claim (`base-persona.md`) | `[destructive-waiver: <reason>]` + backup + verify |
