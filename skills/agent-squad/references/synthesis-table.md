# Cross-Agent Synthesis Table

On-demand template for `orchestrator-contract.md`'s cross-agent synthesis rule. When two or more subagents return handoffs that bear on the same milestone or question, copy this template, fill it, and relay it to the user (or act on it) before doing anything with either handoff alone — never merge silently and never pick a side yourself.

### Agreements

List every point both (or all) agents' returned artifacts independently support — each entry names the agents and the artifact locations, not a paraphrase of "they agree":

- [Point of agreement] — supported by [Agent A]'s `<changed_files>`/`<artifact>` at `path/to/file` and [Agent B]'s at `path/to/file`.
- [Point of agreement] — …

### Tensions

| Tension | Position A (agent) | Position B (agent) | Evidence cited by each | Resolution (decided / needs user) |
|---|---|---|---|---|
| [What the two artifacts disagree about] | [Agent A]: [position] | [Agent B]: [position] | A: `path/file.md#section` or command+output. B: `path/file.md#section` or command+output. | decided: [rule/precedent that settled it] — or — needs user: [the specific question to ask] |

A `Resolution` of "needs user" is not filled in by the Orchestrator picking the more convenient side — it is asked, verbatim, per `orchestrator-contract.md`'s synthesis rule.

### Worked example

**Milestone:** `design/detailed-design.md` data model for the "customer notes" feature, reviewed against `plan.md`'s task breakdown.

#### Agreements

- Notes belong to one customer and one author — supported by Aria's `design/detailed-design.md#data-model` (`customer_notes.customer_id`, `customer_notes.author_id`, both `NOT NULL`) and Alex's `plan.md#task-3` (acceptance criteria assume a single owning customer per note).
- Soft delete is required, not hard delete — supported by Aria's `design/detailed-design.md#data-model` (`deleted_at timestamptz null`) and Alex's `plan.md#task-5` (acceptance criterion: "a deleted note is excluded from list, retained in export").

#### Tensions

| Tension | Position A (agent) | Position B (agent) | Evidence cited by each | Resolution (decided / needs user) |
|---|---|---|---|---|
| Note body storage shape | Aria: a single `body jsonb` column carrying rich-text blocks, for forward compatibility with future block types | Alex: a `body text` column plus a separate `body_format` enum, because the acceptance matrix only tests plain-text rendering this milestone | A: `design/detailed-design.md#data-model`, "Rationale" paragraph under the `customer_notes` table. B: `plan.md#task-4`, acceptance criterion list — none reference block types or a JSON structure | needs user: ship `text` now per the tested scope, or accept `jsonb` now to avoid a migration later — the tradeoff is a schema change against untested speculative flexibility |
| Author reference on delete of the author's account | Aria: `author_id` is `ON DELETE SET NULL`, note survives with an "unknown author" label | Alex: `plan.md#task-6`'s acceptance criterion requires the note to show the original author's name even after account deletion, which `SET NULL` cannot satisfy | A: `design/detailed-design.md#data-model`, FK constraint DDL. B: `plan.md#task-6`, acceptance criterion text (`grep -n "original author" plan.md`) | decided: `author_id` becomes `ON DELETE RESTRICT` plus a denormalized `author_name_snapshot` column, resolving Aria's design toward the tested requirement — no user round-trip needed because `plan.md`'s acceptance criterion is the more specific artifact and Aria's design predates it |

The second row is `decided` without asking the user because one artifact (the acceptance criterion) is strictly more specific than the other and directly falsifies it — see `base-persona.md` § Evidence Integrity on not promoting a narrower artifact over a more specific, later one. The first row stays `needs user` because both positions are internally consistent and the tradeoff is a product decision (ship now vs. avoid a future migration), not a fact either artifact can settle.
