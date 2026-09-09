# ADR Template

Copy this template to `.docs/{project-name}/design/adr/NNNN-<slug>.md` for every design
decision that chooses between **two or more viable options**. `NNNN` is a zero-padded,
monotonically increasing 4-digit sequence number (`0001`, `0002`, …) — never reused, never
renumbered, even if a later ADR supersedes it. `<slug>` is a short kebab-case name for the
decision (`0007-signed-download-links.md`).

An ADR is written once and stands as a historical record. A later decision that changes it
supersedes it — it does not edit it in place (see Status below).

---

```markdown
# ADR-NNNN: <short, decision-shaped title>

## Status

`proposed` | `accepted` | `superseded-by ADR-MMMM`

- `proposed` — drafted, not yet reflected in `detailed-design.md`'s body.
- `accepted` — the design document treats this as settled; this is the terminal
  status for a decision that stands.
- `superseded-by ADR-MMMM` — a later ADR replaced this one. Never delete or
  rewrite a superseded ADR's Decision section; the supersession is recorded here
  and in the new ADR's Context, and the requirement-side annotation points at
  whichever ADR is currently authoritative.

## Context

The forces at play: the requirement(s) driving this decision, constraints (technical,
brief-fixed, timeline), and why a choice is needed now rather than being deferred.

## Decision

The option chosen, stated as a decision ("We will use X"), not a description of X in the
abstract. One paragraph is usually enough; longer explanation belongs in Consequences.

## Alternatives Considered

Every viable option that was NOT chosen, and the specific reason each one lost. "We didn't
think of it" is not a valid entry — an alternative belongs here only if it was genuinely on
the table.

- **<Alternative A>** — <the reason it lost: cost, a constraint it violated, a risk it
  carried that the chosen option does not>.
- **<Alternative B>** — <reason>.

## Consequences

What becomes easier, harder, or newly possible because of this decision — including the
costs accepted, not only the benefits gained. Name any follow-on work this decision creates.

## FR/NFR IDs Affected

Every `FR-n` / `NFR-n` this decision touches. If any of them is thereby superseded or
materially reinterpreted (per `blackgoat-research/SKILL.md` step 6's routing test — does
this decision make any sentence of the requirement false?), that Must-Have/Should-Have
supersession obligation is separate from this ADR and is discharged in
`detailed-design.md`'s `## Divergence & Supersession Register` **and** an in-place
annotation on the requirement in `requirements.md`; this ADR only needs to be cited by that
register row (`ADR-NNNN` or a `adr/NNNN-` path), not to restate the register's contents.

- FR-n — <how this decision affects it>
- NFR-n — <how this decision affects it>
```
