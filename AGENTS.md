---
description: Runtime contract for operating the Blackgoat agent-squad under Google Antigravity. Applies whenever a bgpdd-* pipeline runs or any squad member is delegated to. Claude Code ignores this file.
alwaysApply: true
---

# Blackgoat Squad — Antigravity Runtime Contract

The squad's skills and personas are written **runtime-neutral** — they say "delegate to <Agent>", "read <file>", "write", "run", without naming a specific tool API. This file tells **Antigravity** how to execute that neutral vocabulary. (Claude Code resolves it natively and ignores this file.)

## When this applies

Whenever you invoke a `bgpdd-*` pipeline (`/bgpdd-plan`, `/bgpdd-build`, `/bgpdd-discovery`, `/bgpdd-shipping`, `/bgpdd-lite`) or delegate to any squad member: Rex, Aria, Alex, Mason, Luna, Max, Quinn, Cipher, Dep, Forge, Iris, Scout.

## Load the orchestration model first

When you start any `bgpdd-*` pipeline, first `view_file` on `skills/agent-squad/SKILL.md` and operate under it (the Orchestrator/delegation model, context-integrity check, structured-relay format, project-state tracking). Antigravity does not auto-follow references, so you must read it explicitly.

## "Delegate to <Agent>" means: define → grant → invoke

There is no pre-registered squad subagent to call directly. To delegate:

1. **Read the persona.** `view_file` on `agents/<name>.md`. Take its full body **verbatim** (strip only the YAML frontmatter) as the subagent's `system_prompt` — never summarize or rewrite it. Expand any `{PLUGIN_ROOT}` to this plugin's absolute `skills/` path.
2. **Define with grants.** Call `define_subagent` with that `system_prompt`, setting `enable_write_tools: true` and `enable_mcp_tools: true`. Every worker writes files, runs tests, and may call MCP tools — without these grants the subagent fails or wastes cycles hunting for a way in.
3. **Invoke.** Call `invoke_subagent` with a **compressed briefing** — only the "Working Memory" chunk that agent needs, plus paths to the `.docs/{project-name}/` artifacts it should read. Never paste full prior reports.
4. **Workspace.** Default to `inherit`/`share`; use an isolated `branch` workspace only when explicitly required.

## Subagent lifecycle — OVERRIDES the neutral docs

`agent-squad/SKILL.md` and the `bgpdd-*` pipelines describe a bounded "delegate once, read the returned handoff, there is no kill step" model — that wording is written for Claude Code. **Under Antigravity it does not apply.** Instead:

- Antigravity subagents are **long-lived processes**. After `invoke_subagent`, set a **5-minute (300s) watchdog** with the `schedule` tool, keyed to the subagent's conversation ID.
- Wait for completion **reactively** — do NOT poll `transcript.jsonl` or log files. Antigravity wakes you when the subagent replies or terminates.
- On completion **or** watchdog fire, you **MUST** terminate it: `manage_subagents` with action `kill`. Unkilled subagents leave ghost processes hanging indefinitely.
- If a worker can't finish in one run, have it summarize progress to `.docs/{project-name}/` and terminate; then define+invoke a **fresh** subagent to continue from that handoff.

## Tool mapping (neutral verb → Antigravity tool)

- read / search → `view_file`, `find_by_name`, `list_dir`, `grep_search`
- write / edit → `write_to_file`, `replace_file_content`, `multi_replace_file_content`
- execute → `run_command`

Use these directly. Do NOT reach for Playwright / chrome-devtools to work around a missing write grant — fix the grant (step 2 above).

## Paths

`{PLUGIN_ROOT}` does not auto-expand. Resolve it to this plugin's `skills/` directory (two levels above a skill's `SKILL.md`) and confirm with `list_dir` before passing any path to a subagent.

## MCP & shell

- MCP servers are configured in `mcp_config.json`. For browser/web testing prefer `playwright` or `chrome-devtools-mcp`.
- Prefix shell commands with `rtk` to conserve tokens (e.g. `rtk git status`).
