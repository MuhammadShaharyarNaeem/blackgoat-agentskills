# Reporting — Detailed Design

## 4. Export Delivery

The export artifact is delivered by a short-lived signed download link. See §17 for
every departure from `requirements.md`.

## 17. Divergence & Supersession Register

### 17.1 Divergences

Departures from the playbooks or from a FIXED section of the brief. A divergence does
**not** contradict an FR/NFR — those are §17.2.

| # | Departs from | What this design does instead | Justification |
|---|---|---|---|
| **DIV-01** | **Brief §3 (FIXED):** object storage is S3 | Local disk in dev, S3 in staging and production. | No credentials exist for a dev machine. Cites no requirement. |

### 17.2 Supersessions

Every FR/NFR in `requirements.md` that this design supersedes or materially reinterprets.
**Each row has a matching in-place annotation in `requirements.md`.**

| # | Requirement | What this design does | Why | Annotated |
|---|---|---|---|---|
| **SUP-01** | **FR-2** | A signed download link replaces the scheduled email entirely. | The mail relay is not provisioned in any stage, and a link is auditable. | ✅ FR-2 |
| **SUP-02** | **NFR-1** | The link is signed with a rotating server-side key, not a shared secret. | A shared secret cannot be rotated without invalidating every issued link. | ✅ NFR-1 |
