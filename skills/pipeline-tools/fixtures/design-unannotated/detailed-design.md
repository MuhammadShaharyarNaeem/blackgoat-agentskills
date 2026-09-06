# Reporting — Detailed Design

## 4. Export Delivery

The export artifact (FR-1) is delivered by a short-lived signed download link (NFR-1).

## 17. Divergence & Supersession Register

### 17.1 Divergences

Departures from the playbooks or from a FIXED section of the brief.

| # | Departs from | What this design does instead | Justification |
|---|---|---|---|
| **DIV-01** | **FR-3**'s requesting-user column on the export record | The column is dropped; the object-storage access log is treated as the attribution record instead. | The export row is written by a background worker with no request principal in scope (ADR-0003). |
| **DIV-02** | **FR-9**'s retention window | Retention is left to the storage lifecycle policy. | Cites an ID that requirements.md does not define. |

### 17.2 Supersessions

Every FR/NFR in `requirements.md` that this design supersedes or materially reinterprets.

| # | Requirement | What this design does | Why | Annotated |
|---|---|---|---|---|
| **SUP-01** | **FR-2** | A signed download link replaces the scheduled email entirely. | The mail relay is not provisioned in any stage, and a link is auditable (ADR-0004). | ✅ FR-2 |
