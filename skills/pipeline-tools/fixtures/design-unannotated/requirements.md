# Reporting — Requirements (design filed a divergence but never annotated FR-3)

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As an analyst, I want to export a report, so that I can share it offline.
  - Given a saved report, When I request an export, Then an export file is produced.
- [ ] ~~**FR-2** As an analyst, I want finished exports emailed to me automatically.~~
  > **SUPERSEDED by SUP-01** (`design/detailed-design.md` §17.2). The scheduled email is
  > replaced by a signed download link.
- [ ] **FR-3** As an analyst, I want every export to record the requesting user, so that
      access to a shared report is attributable.
  - Given an export request, When the file is produced, Then the requesting user is recorded.

## Non-Functional Requirements

- **NFR-1** (Must) Security: a signed download link must expire within 15 minutes of issue.
