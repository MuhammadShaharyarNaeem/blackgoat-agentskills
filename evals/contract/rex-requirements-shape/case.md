# Case: rex-requirements-shape

## Purpose
Guards against Rex synthesizing a `requirements.md` that looks plausible but breaks the
machine contract every downstream agent and the pipeline coverage gate depend on:
non-continuous FR numbering (restarting per MoSCoW tier instead of one running
sequence), missing MoSCoW tier headings, or NFRs left without a `(Must|Should|Could)`
tier tag. Per `skills/pipeline-tools/SKILL.md`, an untagged NFR silently defaults to
Must-Have (fail-safe) and emits a warning rather than crashing — so this failure mode
doesn't throw an error, it quietly corrupts coverage accounting downstream. This case
exists to catch that before it reaches Alex or the coverage gate.

## Frozen Input
- Fixture dir: `fixture/` (`rough-idea.md`, `honing-transcript.md` — a small "CSV export
  for user reports" feature, already Q&A'd)
- Copies to: `.docs/csv-export/`

## Command
Run from the temp working copy's root (the parent of `.docs/`):

```powershell
claude -p "Act as Rex per agents/rex.md. Read .docs/csv-export/rough-idea.md and .docs/csv-export/honing-transcript.md, then synthesize .docs/csv-export/requirements.md exactly per Rex's Output Artifacts template in agents/rex.md. Do not ask the user anything - resolve everything from the transcript and put anything unresolved under Open Questions." --permission-mode acceptEdits
```

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/csv-export/requirements.md` exists.
2. Contains a `## Vision` heading.
3. Contains `## Functional Requirements (MoSCoW)` and a `### Must Have` subheading.
4. `**FR-n**` IDs are numbered continuously starting at `FR-1` (no restart per tier, no
   gaps).
5. At least one NFR carries an explicit tier tag: `- **NFR-n** (Must|Should|Could ...)`.
6. Contains a `## Open Questions` heading.

`grade.ps1` exits `0` only if all six pass; otherwise it exits `1` and prints which
criterion (or criteria) failed.

## Runs / Threshold
`runs=5`, pass threshold **4/5**. A single pass proves nothing — Rex's synthesis is run
5 times against the same frozen transcript and must clear the bar on at least 4.

## Future (not implemented)
Quality of *judgment* — did Rex correctly distinguish Must/Should/Could for this
feature, do the acceptance criteria in each FR actually make sense — is not
deterministically checkable and would need an LLM-judge pass. Not implemented here; this
case only checks structural shape.
