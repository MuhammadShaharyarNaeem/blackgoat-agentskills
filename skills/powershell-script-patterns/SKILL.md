---
name: powershell-script-patterns
description: "Provides the PowerShell scripting execution contract: extract embedded scripts to a scratch .ps1 before testing, execute with real stdout/stderr/exit-code capture (never validate by reading alone), escalate un-inferable parameters instead of inventing values, verify every external URL resolves before shipping, and run a static sanity pass (Set-StrictMode, PSScriptAnalyzer). Use when the task involves authoring or modifying PowerShell scripts — standalone .ps1 files or scripts embedded in host-language strings. Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
---

# PowerShell Script Patterns

A PowerShell script is untested theory until it has been executed and its external URLs fetched. Reading a script and declaring it correct is not validation.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Embedded Scripts — Extract, Test, Re-embed

When the script lives inside a host-language string (e.g. a C# string literal, a JSON value, a YAML block):

1. **Extract** the script to a scratch `.ps1` file in your temp/scratch area, unescaping the host language's escaping first (C# `\"` → `"`, `\\` → `\`, `""` inside verbatim strings → `"`, `\n` → newline, string interpolation markers resolved or stubbed). You must test the script the runtime will actually receive, not the escaped source form.
2. **Test** the scratch file per Execution Testing below; iterate on the scratch copy until it passes.
3. **Re-embed** the fixed script into the host string, re-applying the host language's escaping exactly. Confirm the round trip: re-extract (or carefully re-read) the embedded form and verify it matches the tested scratch script.
4. Never make the embedded string your primary edit-test loop — escaping mistakes mask real script errors.

### Execution Testing — Never Validate by Reading Alone

- Run the script: `powershell -NonInteractive -File <scratch>.ps1 [params]` (use `pwsh` if the script targets PowerShell 7+).
- Capture stdout, stderr, AND the exit code. Clean-looking output with a nonzero exit code is a failure.
- Iterate on real errors until the script runs clean, or fails only for an expected environmental reason you can name (requires elevation, a target machine, a domain join). If you could not execute it at all, state that explicitly in your handoff — never report a read-only review as "tested".
- If the script has destructive side effects (deletes, service/registry changes), test through a dry-run or `-WhatIf` path, or stub the destructive step; state in your handoff which paths executed for real.

### Missing Parameters — Escalate, Don't Invent

- If the script requires parameters or values you cannot infer from the codebase or the task brief (tenant IDs, install paths, license keys, service names), do NOT invent plausible-looking values.
- Escalate via your standard `<handoff>` (status BLOCKED, blocker naming the exact parameters and why they are un-inferable). The Orchestrator asks the user — you cannot ask the user directly.

### External URL Verification

- Every download or external URL in a script is untested theory until fetched. Before shipping, verify each one resolves: fetch it (HEAD or a ranged GET, using your shell's HTTP client or web-fetch capability), follow redirects, and confirm the final response is a success from the vendor's current official host — not a 404, a parked domain, or a "this page has moved" notice.
- If a URL is dead or deprecated, research the vendor's actual current official download page, replace the URL, and re-verify the replacement.
- Never trust a URL from model memory — memorized URLs go stale. Every URL you introduce or keep must be verified in this same run.
- If the environment has no network access, flag every unverified URL in your handoff as UNVERIFIED with the reason — never silently ship one.

### Static Sanity Pass

- During scratch testing, run at least one pass with `Set-StrictMode -Version Latest` injected at the top to surface uninitialized variables and invalid property access; remove the injection before re-embedding unless the script already ships with it.
- If PSScriptAnalyzer is available (`Get-Module -ListAvailable PSScriptAnalyzer`), run `Invoke-ScriptAnalyzer -Path <scratch>.ps1` and fix real errors/warnings; suppress a rule only with a stated reason.
- Static passes supplement execution testing; they never replace it.

### Verification Checklist

Before marking work complete:

- [ ] Script was executed, not just read; stdout, stderr, and exit code captured and clean (or the environmental blocker named)
- [ ] If embedded: tested via an extracted scratch `.ps1`; re-embedded form round-trips to the tested script
- [ ] No invented parameter values; un-inferable parameters escalated as BLOCKED
- [ ] Every external URL fetched and confirmed live and official in this run, or explicitly flagged UNVERIFIED with reason
- [ ] Static sanity pass run (StrictMode; PSScriptAnalyzer if installed)

### Escalate When

- Required parameters cannot be inferred → BLOCKED `<handoff>` listing them; do not invent values.
- The script needs an environment you don't have (elevation, target OS, network, licensed software) → `<handoff>` stating exactly what ran and what could not.
- A vendor URL is dead and research cannot identify the current official replacement → `<handoff>` with the candidates you found; do not guess.
