---
name: database-migration-patterns
description: "Provides the database migration execution contract: expand/contract schema evolution, forward-only migrations, two-step deploys, a reviewed idempotent SQL diff artifact, an explicit waiver for destructive operations, batched idempotent backfills, and lock-aware execution. Use if the project changes a relational schema (EF Core primary; generic SQL). Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
---

# Database Migration Patterns

A schema change is the one deploy you cannot revert by redeploying the previous build. Evolve the schema in expand/contract steps, ship the migration ahead of the code that depends on it, and review the generated SQL as a diff before anything runs.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Expand / Contract

Never rename or drop in the same deploy that first reads the new shape. Every schema change decomposes into ordered, independently deployable steps:

1. **Expand** — add the new column/table/index as nullable or defaulted. Old code is unaffected.
2. **Backfill** — populate the new shape from the old (see *Backfills* below).
3. **Migrate reads/writes** — deploy the code that writes both shapes, then reads the new one.
4. **Contract** — drop the old column/table only once no deployed version still reads it.

A rename is an expand + backfill + contract, never an `ALTER ... RENAME` in a single step. A single-step rename breaks every instance running the previous build for the duration of the rollout.

### Forward-Only

- Migrations are **forward-only in production**. Never plan a production recovery around a down-migration: a down-migration that drops a column destroys the data written since the up-migration ran, and one whose up-step was partially applied may not be runnable at all.
- Down-migrations may exist for local development. They are not a rollback plan and are never cited as one.

### Two-Step Deploy

The migration deploys **separately from, and before, the code that depends on it**. One deploy applies the schema change; a subsequent deploy ships the code that uses it. A migration bundled into the same release as its consuming code has no safe intermediate state — a failed app rollout leaves a schema no running version matches.

### The Reviewed SQL Diff Artifact

Generate the migration as SQL and review it as a diff before it runs anywhere:

- EF Core: `dotnet ef migrations script --idempotent --from <previous> --to <target>` (stack equivalent otherwise — e.g. the ORM's `--sql`/`--dry-run` script mode).
- Save the output to `.docs/{project-name}/implementation/evidence/migration/<name>.sql` and cite that path in your `<handoff>`.
- Read the generated SQL. An auto-generated migration routinely contains an operation the model change did not intend — a dropped index, a re-created constraint, a table rebuild. An unread script is an unperformed check (`base-persona.md`, Evidence Integrity).
- Scripts are **idempotent**, so a partially-applied migration can be re-run safely.

### Destructive Operations Require an Explicit Waiver

`DROP TABLE`/`DROP COLUMN`, column narrowing (length or precision reduction), adding `NOT NULL` to a populated column, and type changes are **destructive**: they can lose data that no rollback restores. Each one requires, in the plan task that authorizes it, an explicit

```
[destructive-waiver: <reason>]
```

plus a backup step and a verify step (the backup exists, is readable, and the row count matches) run **before** the destructive statement. No waiver in the task → return the task unbuilt as a planning defect; NEVER add the waiver yourself.

### Rollback

The rollback for a migration is **a tested forward migration or a verified restore** — never "run the down-migration".

- Write it, run it on non-prod against prod-shaped data, **time it**, and record the measured duration alongside the migration artifact.
- The bound it must fit is the database tier of `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` (Rollback Strategy → *Time to Rollback*, `< 15 minutes`); that skill owns the number. A rollback that cannot be executed within it is an escalation before the deploy, not a footnote after it.

### Backfills

- **Batched**: iterate in bounded chunks with a stable ordering key; never a single unbounded `UPDATE` across the table.
- **Idempotent**: re-running the backfill from the start produces the same result — filter on the rows still needing work, never on a position the process has to remember.
- **Resumable and observable**: log progress per batch so an interrupted run can be restarted at the right place.
- Long backfills run as a separate job, not inside the migration transaction.

### Concurrency & Locks

- Avoid operations that hold a long exclusive lock on a live table. Check what the target engine's version actually locks — the same DDL is online on one engine and a full table rewrite on another.
- Create indexes online where the engine supports it (`CREATE INDEX CONCURRENTLY`, `WITH (ONLINE = ON)`); otherwise schedule the operation in a maintenance window and say so in the plan task.
- Set a lock timeout so a blocked migration fails fast instead of queueing every request behind it.
- Add columns without a volatile default on large tables; backfill separately.

### Verification Checklist

Before marking migration work complete:

- [ ] Generated SQL script reviewed as a diff and saved under `.docs/{project-name}/implementation/evidence/migration/`
- [ ] Script applied cleanly to a copy of prod-shaped data (not an empty dev database)
- [ ] The app boots and serves against the new schema with **both** the old and the new code version
- [ ] Every destructive operation carries its `[destructive-waiver: <reason>]`, backup, and verify step
- [ ] Rollback (forward migration or restore) rehearsed on non-prod and its measured duration recorded
- [ ] Backfill re-run from the start on non-prod produces an unchanged result

### Escalate When

- A required change has no non-destructive expand/contract decomposition (an irreversible migration) → escalate to the Orchestrator **before** deploying, matching `shipping-and-launch`'s "no viable rollback plan" escalation.
- A plan task asks for a destructive operation with no `[destructive-waiver:]` → return unbuilt as a planning defect.
- The rehearsed rollback exceeds the `shipping-and-launch` database tier, or no prod-shaped dataset exists to rehearse against → report to the Orchestrator; `BLOCKED`, never `PASS`.
- The migration requires downtime or a maintenance window the plan does not authorize → escalate; never take the lock and hope.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Migration deep dive](references/migration-deep-dive.md) — the worked expand/contract rename, EF Core command reference and generated-script hazards, batched-backfill shape, per-engine lock notes, and the anti-pattern table.
