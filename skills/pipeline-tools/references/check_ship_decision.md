# check_ship_decision.py — reference

Depth for the `check_ship_decision.py` section of `../SKILL.md`: the parsing rules and the documented divergence from the eval grader.

### Parsing rules (condensed)

- **Verdict line**: a line starting (after any `#`/`>`/`-`/`*`/whitespace) with `Ship Decision`, `Verdict` or `Recommendation` and containing the token `GO` or `NO-GO` (`NOGO`/`NO GO` normalize to `NO-GO`).
- **Last-section-wins**: the file is split at markdown headings, and only the **LAST** verdict-bearing section is read. This mirrors `check_agent_report.py` and exists because `bgpdd-shipping` Step 3 instructs the re-verifying agent to **append** a fresh section after a fix round — a Round-2 `GO` must be able to supersede a Round-1 `NO-GO`. Judging ambiguity file-wide made an appended document permanently unpassable.
- **Ambiguity** is still caught *within* the winning section: a section stating both `GO` and `NO-GO` fails, verdict `null`.
- **Rollback**: any heading (levels 1–6) whose text contains "rollback".
- **Checklist**: any heading containing "checklist", **OR** at least 3 `- [ ]`/`- [x]` checkbox items. **Scope limit**: a checklist heading with zero items under it satisfies this check — deliberate parity with `evals/contract/dep-ship-decision-shape` criterion 5, not an oversight. The gate proves a decision is machine-readable, never that its checklist is populated or its verdict correct.
- **Divergence from the eval's `grade.ps1`**: that script counts verdicts file-wide (correct for the single-shot document its prompt produces); this gate scopes to the latest section (required for a pipeline artifact that gets appended to across fix rounds). The two agree on every single-section document.
