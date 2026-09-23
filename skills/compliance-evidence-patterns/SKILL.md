---
name: compliance-evidence-patterns
description: "Provides the compliance-evidence execution contract: an Evidence Collection Matrix mapping each in-scope control to the named framework clause, the artifact that proves it and how that artifact is collected; the rule that an unproven control is an open finding; the DPIA trigger checklist; and the Likelihood x Severity risk score with its escalation threshold. Use if the project claims SOC 2, ISO 27001, or GDPR obligations, or changes how personal data is processed. Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
---

# Compliance Evidence Patterns

A control nobody can produce evidence for is not a control — it is an assumption with a reference number. This contract turns a claimed obligation into a row that names its proof, and turns a claim with no row into a finding rather than a silence. It owns the *evidence* half of Ward's audit; the engineering controls themselves (minimization, lawful basis, retention, deletion paths) belong to `{PLUGIN_ROOT}/privacy-engineering-patterns/SKILL.md`, and the security controls to `{PLUGIN_ROOT}/security-and-hardening/SKILL.md`.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### The Evidence Collection Matrix (durable artifact)

Every audit round writes or updates `.docs/{project-name}/implementation/evidence-matrix.md`. It carries exactly this column header line, verbatim, so a future gate can parse it:

```
| Control ID | Framework clause | Evidence artifact | Source system | Collection method | Frequency |
```

One row per in-scope control, and:

- **Framework clause is named, never paraphrased** — `SOC 2 TSC CC6.1`, `ISO 27001 Annex A 8.15`, `GDPR Art. 30(1)(f)`. "Access control requirements" is not a clause; an auditor cannot sample against it and the next round cannot tell whether scope changed.
- **Evidence artifact is a thing that exists** — an access-review export, a retention config, a signed DPA, a capture under `evidence/`. A process description is not an artifact.
- **Collection method is re-runnable or located.** Where the evidence can be produced by a command, the cell holds that command as run through `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture .docs/{project-name}/implementation/evidence/compliance/<control>.md --ledger .docs/{project-name}/implementation/gates.jsonl -- <command>`. Where it cannot (a board-approved policy, a vendor's SOC 2 report, a signed DPA), the cell names **the document and where it lives** — never "manual" alone, which records only that nobody looked.
- **Frequency is the collection cadence** — per event / monthly / quarterly / annual / per release. A control whose evidence is older than its own cadence is stale, and a stale row reports `FAIL`, not `PASS`.

**No gate parses this file yet** — it is read by Ward and cited from the report; the parseable header line exists so the lane that consumes it can be given one without re-authoring every matrix (CLAUDE.md, *Adding a New Agent or Methodology Skill*: a skill arrives with a gate or a lane, and the lane here is `bgpdd-secure`, which consumes the matrix through Ward's `privacy-report.md`).

### An Unproven Control Is An Open Finding

A control that is in scope and has no evidence row is written as a `FAIL` check line in `.docs/{project-name}/implementation/privacy-report.md`, named `control-<id>`. It is **never omitted, and never silently dropped from scope**: scope is set once, at the top of the round's section, and a control leaves it only by an explicit `Not applicable — <reason>` row in the matrix.

This is deliberately **tighter than base-persona Evidence Integrity's default** (convention #8), which sends an unrun check to `BLOCKED`: an in-scope control with no evidence row is not an unrun check, it is a known gap, and `BLOCKED` would let a round close with the gap unclassified.

### DPIA Trigger Checklist

Evaluate every one of these against the change under audit, not against the product as a whole (GDPR Art. 35). Any box ticked means a DPIA is required **before the change ships** — never after:

- [ ] Systematic, extensive automated profiling or scoring with significant effects on people
- [ ] Large-scale processing of special-category or criminal-offence data
- [ ] Systematic monitoring of a publicly accessible area
- [ ] A new technology applied to personal data — AI/ML inference, biometrics, IoT telemetry, behavioural tracking
- [ ] Large-scale processing affecting a large number of data subjects
- [ ] Datasets combined or enriched in a way data subjects would not expect
- [ ] Invisible processing — the data subject is never told it happens
- [ ] Processing that blocks a right or conditions access to a service on it

The evaluation is the `dpia-trigger-review` check line. If a trigger fires and no DPIA exists, that line is `FAIL` and a `**Critical**` finding names the trigger.

### Likelihood x Severity, and the number that stops the round

Each identified privacy risk is scored **Likelihood (1–5) x Severity (1–5) = risk score**, severity measured as harm to the data subject — not to the system. This ordering is a deliberate divergence from `{PLUGIN_ROOT}/security-and-hardening/SKILL.md` (*The Assurance Case Artifact*), which orders by proven exploitability (convention #8): the asset at risk here is the person, and an unlikely-but-devastating disclosure outranks a probable annoyance.

**Threshold: a residual risk scoring above 15 blocks the round.** The action is not "consider escalating": the risk is written as a `**Critical**` finding line, and the check line `dpia-risk-threshold` reports `FAIL`. Both are terms `check_agent_report.py` already grades — a standing Critical blocks `Pass` on its own, and a `FAIL` line puts the gate at exit 1 — so the restraint is enforced by a script the Orchestrator has to run, not by this paragraph (convention #9). No new gate is written for it; the existing one already refuses the verdict. Residual means *after* the mitigations you recorded, not before.

### Check lines this skill contributes

They go in Ward's `privacy-report.md` under its `## Privacy & Compliance Audit: <scope> — <date>` section, in the check-line grammar owned by `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` (§ `check_agent_report.py`) — read it there; this skill contributes **names and what each capture must prove**, never a variant grammar. Captures live under `evidence/compliance/`.

| Check name | What its capture must prove |
|---|---|
| `evidence-matrix-complete` | Every in-scope control has a matrix row, and the row count matches the declared scope count — the command counts both and exits non-zero on a mismatch |
| `evidence-freshness` | No row's evidence is older than that row's own Frequency cell |
| `control-<id>` | The named artifact for that one control was produced by the row's collection method, on this round — one line per sampled control, the id exactly as the matrix spells it |
| `dpia-trigger-review` | The eight triggers were evaluated against this change, and the DPIA exists where one fired |
| `dpia-risk-threshold` | Every scored risk's residual score, and that none stands above 15 |

A finding that elaborates one of these lines is written **directly under it** — that placement is what gives the finding its category when a rescan is diffed (`{PLUGIN_ROOT}/bgpdd-secure/SKILL.md`, Phase 2, owns the placement rule). A control whose source system was unreachable is `BLOCKED` with that reason — never `PASS`, never omitted (`{PLUGIN_ROOT}/agent-squad/base-persona.md`, Evidence Integrity).

### What stays prose, and why

Framework scoping, sampling size, policy authorship and auditor correspondence stay prose here. Convention #9 converts a rule that asks an agent to restrain itself at the moment it most wants to proceed; these are **decisions made at brief time**, before any verdict is in reach, and they are inputs an Orchestrator sets — not a temptation at the point of closing a round. The two rules that *are* such a temptation — dropping an unprovable control, and verdicting past a high residual risk — are the two converted above.

### Escalate When

- A control is in scope but its evidence lives in a system you cannot reach → report `BLOCKED` with the system named, and escalate to the Orchestrator; never infer the control from an adjacent one.
- A DPIA trigger fires on a change already merged or shipped → escalate to the Orchestrator immediately; the assessment is now overdue, and that is a routing decision, not yours to schedule.
- A residual risk stands above 15 with no available mitigation → escalate to the Orchestrator with the score and the mitigations already tried; supervisory-authority consultation is a human decision.
- The scope itself is undefined — no framework named in the brief → return the round unstarted as a planning defect rather than choosing a framework yourself.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Compliance rationale](references/compliance-rationale.md) — why the matrix is one row per control rather than per system, worked matrix rows for SOC 2 / ISO 27001 / GDPR, the common-control mapping that stops one control being evidenced three times, DPIA report structure and the mitigation table, breach-clock and vendor-DPA adjacency, and the failure modes this contract exists to stop.
