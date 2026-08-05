# Reporting — Requirements (annotated after design)

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As an analyst, I want to export a report, so that I can share it offline.
  - Given a saved report, When I request an export, Then an export file is produced.
- [ ] ~~**FR-2** As an analyst, I want finished exports emailed to me automatically.~~ — superseded by D-3 (design §4.2 replaces scheduled email with a signed download link)
  - Given a completed export, When it becomes available, Then the analyst is given a signed download link.

### Should Have

- [ ] **FR-3** As an analyst, I want an export history list, so that I can re-download past exports.

### Won't Have (this version)

- Scheduled recurring exports are out of scope for this release.

## Non-Functional Requirements

- **NFR-1** (Must) Security: a signed download link must expire within 15 minutes of issue.
- **NFR-2** (Should) Observability: export failures must be logged with the requesting user.
