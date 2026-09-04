# check_ship_decision.py — reference

Depth for the `check_ship_decision.py` section of `../SKILL.md`: the parsing rules, the rehearsal and baseline flags, and the documented divergence from the eval grader.

### Parsing rules (condensed)

- **Verdict line**: a line starting (after any `#`/`>`/`-`/`*`/whitespace) with `Ship Decision`, `Verdict` or `Recommendation` and containing the token `GO` or `NO-GO` (`NOGO`/`NO GO` normalize to `NO-GO`).
- **Last-section-wins**: the file is split at markdown headings, and only the **LAST** verdict-bearing section is read. This mirrors `check_agent_report.py` and exists because `bgpdd-shipping` Step 3 instructs the re-verifying agent to **append** a fresh section after a fix round — a Round-2 `GO` must be able to supersede a Round-1 `NO-GO`. Judging ambiguity file-wide made an appended document permanently unpassable.
- **Ambiguity** is still caught *within* the winning section: a section stating both `GO` and `NO-GO` fails, verdict `null`.
- **Rollback**: any heading (levels 1–6) whose text contains "rollback".
- **Checklist**: any heading containing "checklist", **OR** at least 3 `- [ ]`/`- [x]` checkbox items. **Scope limit**: a checklist heading with zero items under it satisfies this check — deliberate parity with `evals/contract/dep-ship-decision-shape` criterion 5, not an oversight. The gate proves a decision is machine-readable, never that its checklist is populated or its verdict correct.
- **Divergence from the eval's `grade.ps1`**: that script counts verdicts file-wide (correct for the single-shot document its prompt produces); this gate scopes to the latest section (required for a pipeline artifact that gets appended to across fix rounds). The two agree on every single-section document.

### `--require-rehearsal` — a plan is not a rehearsal

The base gate accepted any `/rollback/` heading, which is a *plan*. The grammar the flag demands is in the spine; the rules around it are here.

- **`env` is recorded, not judged.** "Non-production" is a producer-side rule in `shipping-and-launch`; the gate stores whatever string was written. A gate that tried to classify environment names would be guessing.
- **Last-line-wins, file-wide.** A fix round re-records the line, and the newer rehearsal must supersede the older one — the same reason the verdict parser is last-section-wins. Fences are stripped first, so a template line inside a code block never wins.
- An impossible calendar date reads as `rehearsal_missing`, not as a stale rehearsal: an unparseable date is not a rehearsal that happened too long ago, it is a line that does not conform.
- **Provenance** is a containment scan for `evidence/rollback` plus no `..` segment, plus: the path exists, is non-empty, carries a `## Captured output` section, and has a sidecar JSON whose `capture_sha256` matches the capture file's bytes and whose `exit_code` is `0`. A non-zero exit is `rehearsal_failed_exit` — **a failed revert-plus-health-check proves the rollback does not work**, which is a worse result than no rehearsal at all, so it gets its own code rather than being folded into "unevidenced".
- **There is deliberately no `--allow-missing-sidecar` equivalent** (convention #8, diverging from `check_runtime_evidence.py`'s precedent): a legacy capture can predate the sidecar rule, but a rehearsal is performed on purpose, after this flag existed, so there is no legacy population to waive for.
- **Staleness** is measured against today UTC; a future date is not stale. The fix for `rehearsal_stale` is to **re-run the rehearsal, never to re-date the line**.
- `time_s` is normalized from whatever unit was written, so the value is comparable across decisions.
- **Scope limit**: the gate does not enforce `shipping-and-launch`'s Time-to-Rollback tier ladder, because the rollback *type* is not machine-readable from the decision document. Fitting the recorded time to the ladder stays a producer-side rule, labelled convention #8 there.

### `--require-baseline` — the threshold table is deltas all the way down

Every cell in the Rollout Decision Thresholds table is a **delta** ("error rate up 2x", "p95 up 50%"). Without a recorded baseline each row resolved against the reader's memory of normal, so the canary could never actually fail.

- The section is the first `##` or `###` heading whose text is `Baseline`, and it ends at the next heading of level ≤ its own.
- It must hold **at least 3** `- <metric>: <value>` lines. **Metric names are not checked** — which three metrics matter is a per-project business judgment, and a gate with a fixed list would be wrong for most projects.
- Each line must cite a path under `evidence/baseline/` that exists. There is **no sidecar requirement** here, unlike the rehearsal: a baseline is typically read off a monitoring dashboard by a human, and there is no tool-written capture to hash.

### Fixtures and self-test

Two fixture trees: `ship-decision-rehearsed/` (exit 0 bare and under both flags — a rehearsal capture plus its sidecar plus three baseline readings, with `.gitattributes` `-text` so the hashed bytes survive checkout) and `ship-decision-unrehearsed/` (the pre-change shape: exit 0 bare, exit 1 under either flag).

**Wall-clock limitation**: the rehearsed fixture's date is fixed at `2026-08-28`, so from `2026-09-28` onward it needs `--max-rehearsal-age-days <large>` or a date bump. The staleness logic itself is covered in the self-test with a synthetic "today" rather than the real clock. **47** cases.
