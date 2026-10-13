# Deployment Manifest Template

Fillable skeleton for `.docs/{project-name}/deploy/manifest.md`. Rules: `../SKILL.md` § Deployment Manifest. Gate and contract of record: `check_deploy_manifest.py --help`. Delete the guidance comments when filling it in.

```markdown
# Deployment Manifest — {project-name}

Plan: `../implementation/plan.md`
Target: <environment(s), e.g. Azure prod — subscription/resource group by name, never by secret>

<!-- Rows in the order production applies them. Type: sql | azure | appsetting | secret | flag | backfill | other.
     Status: drafted | pending-build | final. Script/Rollback paths are relative to this file's directory.
     Rollback with no script: [no rollback: <reason>]. Traces: plan task number(s), e.g. 3 or 3, 5.
     sql rows stay pending-build, naming the Script/Rollback paths they will hold (not yet on disk), until build Phase 5 copies in the reviewed idempotent migration diff.
     backfill and other rows may be drafted (script on disk) or pending-build (paths named, written at build Phase 5 from the code as built). -->

| # | Type | Step | Script | Rollback | Traces | Status |
|---|------|------|--------|----------|--------|--------|
| 1 | sql | <expand: add column / table> | scripts/01-schema.sql | rollback/01-schema.sql | <task> | pending-build |
| 2 | secret | <create Key Vault secret `<name>` (name only, no value)> | scripts/02-secret-<name>.ps1 | rollback/02-secret-<name>.ps1 | <task> | drafted |
| 3 | appsetting | <set `<Key>` → Key Vault reference `<name>`> | scripts/03-appsetting-<key>.ps1 | rollback/03-appsetting-<key>.ps1 | <task> | drafted |
| 4 | azure | <create/alter resource `<name>`> | scripts/04-azure-<resource>.bicep | rollback/04-azure-<resource>.ps1 | <task> | drafted |
| 5 | flag | <declare flag `<name>`, default off in prod> | scripts/05-flag-<name>.ps1 | rollback/05-flag-<name>.ps1 | <task> | drafted |
| 6 | backfill | <batched idempotent backfill of `<table>`> | scripts/06-backfill-<table>.sql | [no rollback: <reason>] | <task> | drafted |

<!-- Nothing to deploy: keep the header row and separator, no data rows, and replace this comment with:
No production changes: <reason> -->
```
