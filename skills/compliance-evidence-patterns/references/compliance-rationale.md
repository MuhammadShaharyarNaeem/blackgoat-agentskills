# Compliance Evidence — Rationale and Worked Material

Depth for `compliance-evidence-patterns/SKILL.md`. Nothing here is needed to execute the contract; read it when a matrix row is hard to write, when one control has to satisfy three frameworks, or when a DPIA is actually owed.

## Why one row per control, not per system

The instinct is to inventory systems — "Okta, AWS, Jira, the warehouse" — and list what each one can produce. That inventory is genuinely useful and it is not an evidence matrix, because nothing in it fails. A system either exports or it does not; an auditor samples a *control*, and a control is what can be absent. Rows keyed by control ID make absence visible as a missing row; rows keyed by system make absence invisible, because the system is still in the list, still exporting something, still looking healthy.

The same reasoning is why scope is declared once at the top of a round and a control only leaves it by an explicit `Not applicable — <reason>` row. A control quietly dropped between rounds reads exactly like a control that never applied, and the two are the difference between a scoping decision and a gap.

## Worked matrix rows

```
| Control ID | Framework clause | Evidence artifact | Source system | Collection method | Frequency |
|---|---|---|---|---|---|
| AC-01 | SOC 2 TSC CC6.1 | Quarterly access review export (all human IAM principals) | Identity provider | `run_quiet.py --capture evidence/compliance/ac-01.md -- <idp-cli> users list --format json` | Quarterly |
| AC-03 | SOC 2 TSC CC6.2 | Deprovisioning record per leaver | HR system + identity provider | Named doc: `docs/policies/offboarding.md` + the ticket queue's saved filter "Offboarding — closed" | Per event |
| LOG-02 | ISO 27001 Annex A 8.15 | Log-redaction test output over the PII field list | Application repo | `run_quiet.py --capture evidence/compliance/log-02.md -- <test-runner> --filter RedactionTests` | Per release |
| RET-01 | GDPR Art. 5(1)(e) | Retention period stated per store holding a PII class | Application repo | `run_quiet.py --capture evidence/compliance/ret-01.md -- <search> -n "retention" config/` | Per release |
| ROP-01 | GDPR Art. 30(1) | Article 30 register, current version | Privacy program | Named doc: `.docs/{project-name}/implementation/article-30-register.md` | Annual + on change |
| VEN-02 | GDPR Art. 28(3) | Signed DPA with each processor handling personal data | Contract store | Named doc: the vendor folder, one signed DPA per processor named in ROP-01 | Annual |
```

Three things the rows are demonstrating:

1. A command cell is re-runnable **as argv** — no pipes, no redirects, no `&&`. `run_quiet.py` spawns argv with no shell, and `check_agent_report.py` compares the command on the check line against the capture's recorded `argv` on token lists. A cell containing `| wc -l` produces a capture that cannot back the line that cites it.
2. A non-command cell names a document **and its location**. "Manual collection" records only that nobody looked; "the vendor folder, one signed DPA per processor named in ROP-01" is checkable by a person in a minute.
3. Frequency is the cadence the evidence must beat. `Per release` on a code-resident control means the capture is retaken on the round, not inherited from the last one.

## One control, three frameworks

Most obligations overlap, and the expensive failure mode is evidencing the same control three times because three framework tables were built independently. Map to a **common control** and cite the clauses side by side in one row:

```
| AC-01 | SOC 2 TSC CC6.1; ISO 27001 Annex A 5.18; GDPR Art. 32(1)(b) | ... |
```

One artifact, one collection run, three clauses satisfied. What must *not* be merged is two controls that happen to share an artifact but differ in what they assert — an access-review export proves review happened, not that provisioning was authorized. If the two assertions could fail independently, they are two rows.

## DPIA report structure

When a trigger fires, the assessment is a document, not a paragraph in the report. Six sections:

1. **Description of processing** — purpose, nature, scope (data subjects, volume, frequency, duration), data types and sensitivity, processors and recipients.
2. **Necessity and proportionality** — is the processing necessary for the stated purpose; is there a less intrusive alternative; lawful basis; how minimization was applied. This section is where "we do not need this field" gets written down, and it is the only section that can reduce the risk score to zero.
3. **Risk assessment** — one row per risk: risk, Likelihood (1–5), Severity (1–5), score, mitigant. Severity is harm to the data subject.
4. **Measures** — per risk: technical, organizational, contractual.
5. **Residual risk and opinion** — the score *after* section 4, with sign-off and any conditions.
6. **Supervisory-authority consultation** — required where residual risk stays high (Art. 36).

Typical risks worth pre-populating: unauthorized access to personal data; data subject unable to exercise a right; retention beyond purpose; cross-border transfer without a safeguard; re-identification of pseudonymized data.

## Why the threshold is a number and not a judgement

A qualitative scale ("high risk") is re-read at the moment of closing a round by the person who wants the round closed, and "high" quietly becomes "elevated". `Likelihood x Severity > 15` is arithmetic: it produces the same answer on a Friday afternoon. The number also has to *do* something, which is why the contract spends it on two artifacts `check_agent_report.py` already grades (a `**Critical**` finding and a `FAIL` check line) rather than on an instruction to escalate — an instruction to escalate is exactly the prose convention #9 exists to replace.

15 is the conventional DPIA cutoff (a 3x5 or 5x3 — a severe harm that is not remote, or a near-certain harm that is not trivial). It is a threshold, not a physical constant; a project with a stricter bar declares it in the brief, and the declared bar is what the check line grades.

## Adjacent obligations this contract does not own

- **Breach notification.** GDPR's 72-hour clock starts at *awareness*, not at confirmation. If an audit round uncovers an actual disclosure rather than a control gap, that is an incident: escalate to the Orchestrator rather than filing it as a finding, because the clock is already running and the response is a human decision.
- **Vendor due diligence.** The matrix records whether a DPA exists and covers the processing (Art. 28(3)); negotiating one, and the transfer mechanism behind it (adequacy, SCCs, BCRs, a transfer impact assessment), is not agent work.
- **Legal determination.** This contract produces evidence and findings. Whether a processing activity is lawful as designed is advice a qualified practitioner gives; a finding may say "no documented lawful basis for <activity>" and must not say which basis to claim.

## Failure modes this contract exists to stop

- **The control that was never in scope.** A gap disappears by never appearing. Answered by: scope declared once, and a missing row is a `FAIL` check line named `control-<id>`, not an omission.
- **Evidence that proves existence, not operation.** A screenshot of a configuration page proves the setting is on today. An audit period asks whether it was on throughout. Answered by: Frequency, and a `FAIL` on a row whose evidence is older than its own cadence.
- **The DPIA written after launch.** A DPIA that ratifies a shipped design is a document, not an assessment — every mitigation it could have proposed is now a migration. Answered by: the trigger checklist is evaluated against the change, and a fired trigger on merged work escalates rather than files.
- **The mitigated-on-paper risk.** A residual score copied from the pre-mitigation column, or a mitigation listed as "planned". Answered by: residual means after the mitigations you recorded, and a mitigation that is not yet in place does not reduce the score.
