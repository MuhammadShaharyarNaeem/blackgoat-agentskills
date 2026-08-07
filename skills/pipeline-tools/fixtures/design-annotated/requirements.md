# Reporting — Requirements (annotated after design)

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As an analyst, I want to export a report, so that I can share it offline.
  - Given a saved report, When I request an export, Then an export file is produced.
- [ ] ~~**FR-2** As an analyst, I want finished exports emailed to me automatically.~~
  > **SUPERSEDED by SUP-01** (`design/detailed-design.md` §17.2). The scheduled email is
  > replaced by a signed download link.

### Should Have

- [ ] **FR-3** As an analyst, I want an export history list, so that I can re-download past exports.

## Non-Functional Requirements

- **NFR-1** (Must) Security: a signed download link must expire within 15 minutes of issue.
  > **"shared secret in the link" superseded by SUP-02** (`design/detailed-design.md` §17.2).
  > The link is signed with a rotating server-side key instead.
- **NFR-2** (Should) Observability: export failures must be logged with the requesting user.
