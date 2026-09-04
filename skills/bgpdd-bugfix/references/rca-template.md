# RCA template (`/bgpdd-bugfix` Phase 2)

The Orchestrator writes `{bugfix-root}/rca.md` in the main session. Two gates
read it, so the `- Key: value` lines below are a **machine-read contract**, not
prose formatting:

- `next_bugfix_route.py --rca` reads `- Root cause file:` (repeatable),
  `- Baseline suite:`, `- New capability:`, `- Schema or contract change:` and
  `- Estimated changed files:` to decide FAST | FULL | PLAN. A missing one of
  the first four is `INCOMPLETE` (exit 1) — the route is refused, not guessed.
- `check_commit_gate.py --waiver` reads the `## Size waiver` section, and only
  when `--max-changed-files` is also passed.

Field rules:

- **`- Root cause file:`** — one line per file the defect actually lives in.
  Exactly one is a FAST-route term; two or more is legitimate but routes FULL.
- **`- Baseline suite:`** — `green` | `red` | `not run`. This records what the
  suite did **before** the fix. Only `green` allows FAST: a suite that was
  already red cannot tell this fix's regression from the standing one.
- **`- New capability:`** and **`- Schema or contract change:`** — `yes` | `no`.
  Either `yes` routes PLAN: that is build work, not a bugfix.
- **`- Estimated changed files:`** — an integer. Over the lane's bound (5)
  routes PLAN. Omitting the line warns and leaves the bound to the commit gate.
- A field line **inside a fenced block** asserts nothing (the gate blanks
  fences). Last mention of a key file-wide wins, so an appended `## Correction`
  section supersedes an earlier line.

**Hypothesis ledger.** One row per hypothesis, with the read that would have
disproved it and what that read actually showed. The disproof rule itself is
the Orchestrator Contract §3a's — this section is where its output lands, and a
row whose "Disproof attempt" column names no executed read or command is not a
disproved hypothesis, it is a preference.

**`## Size waiver`** is written ONLY when the fix genuinely exceeds the file
bound and the user has said to proceed anyway. It is hand-typed on purpose: the
waiver is the **user's decision, recorded** — no gate can verify a judgement
call, and the value here is that the decision is attributable and durable
rather than spoken once in chat. The gate checks only that the section exists
and is non-empty.

---

Everything below the next line is the document body.

---

# RCA: {bug-slug}

## Hypothesis ledger

| Hypothesis | Disproof attempt (the read or command run) | Result |
|---|---|---|
| <the leading hypothesis> | <the cheapest read that would disprove it> | <disproved — what it showed / survived — what it showed> |

## Root cause

<The specific mechanism of the failure, in one or two sentences: what value
reaches what code path and why that path is wrong. Not a symptom restatement.>

- Root cause file: `<path/to/the/file.ext>`

## Fix shape

- Baseline suite: <green | red | not run>
- New capability: <yes | no>
- Schema or contract change: <yes | no>
- Estimated changed files: <N>

## Size waiver

<Delete this whole section unless the fix exceeds the file bound. When it does:
one or two sentences naming how many files, why the bound cannot be met, and
that the user approved proceeding — with the date. Read by
`check_commit_gate.py --waiver`.>
