# Bug report template (`/bgpdd-bugfix` Phase 0)

Copy this file to `{bugfix-root}/bug-report.md` and replace **every** `<...>`
placeholder. The Orchestrator writes it in the main session with the user, then
runs:

```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/check_bugfix_intake.py \
    --report {bugfix-root}/bug-report.md --milestone "{bug-slug}" \
    --ledger {bugfix-root}/gates.jsonl
```

**This template is written to FAIL that gate** — every placeholder is one the
gate rejects, so "copy the template and run the gate" is not a bypass. Its own
failure is asserted by `check_bugfix_intake.py --self-test`
(`test_the_shipped_template_fails_the_gate`).

Field rules the gate enforces, in the words it uses:

- Every section below must be present and hold real content — not `<...>`, not
  `TODO`/`TBD`/`N/A`.
- **Reproduction** needs **either** a usable `- Command:` line **or** at least
  **two** numbered steps. One step is not a reproduction.
- A `- Command:` value must be **backtick-wrapped** and a **single
  argv-runnable command**: no pipes, no redirects, no `&&`, no shell
  one-liners. Quinn runs it through `run_quiet.py`, which executes argv
  directly with no shell, and Phase 2's route gate compares the recorded argv
  against this line. Quoting *is* fine and is handled — `-d '{"a":1}'` and
  `-H "Content-Type: application/json"` both match, because the comparison is
  on token lists rather than strings. If the reproduction genuinely needs a
  shell, put it in a script and name the script here.
- **`- Surface:`** must be exactly `api`, `ui`, or `both`. The unanswered
  `api | ui | both` line fails.
- **`- Runtime observable:`** must be exactly `yes` or `no`. `yes` means the
  wrong behaviour is visible at a boundary a client, person, or device reaches
  (a response body/status/header, a rendered state, a device effect) — that is
  what routes the fix through `check_runtime_evidence.py` in Phase 4. `no` means
  a pure logic defect provable by a test run alone.
- **`- Regression:`** must be exactly `yes` or `no`. A `yes` also needs a real
  `- Last known good:` value — there is nothing to bisect between without one.

A fenced block counts as content (a pasted log is exactly what the error section
is for), but a heading or a `- Key: value` line **inside** a fence satisfies
nothing.

**Arriving from an escalated `/bgpdd-quick`?** That lane's `{quick-root}/note.md`
may pre-fill two fields as **drafts**: its `- What:` line seeds *Observed
behaviour*, and its `- How verified:` line seeds the *Reproduction*
`- Command:`. Nothing else carries over, and the intake gate lints both exactly
as if you had typed them — a draft that is not really a reproduction still fails.

- **Fields may be pre-filled from telemetry.** When an incident produced this report, Observed behaviour, the error text, Environment and the first-seen timestamp are copied from the alert, log excerpt or trace rather than typed from memory (`{PLUGIN_ROOT}/observability-and-diagnosis/SKILL.md`). Pre-filled is still linted: a pasted log excerpt satisfies the error section, an unanswered `<...>` does not.

---

Everything below the next line is the report body. Copy from there down.

---

# Bug report: <one-line title>

## Observed behaviour

<What actually happens, in one or two sentences. Behaviour only — no diagnosis;
the root cause belongs in rca.md, written in Phase 2.>

## Expected behaviour

<What should happen instead, and what says so — a requirement ID, a contract, a
documented behaviour, or the user's stated expectation.>

## Exact error text or log excerpt

```
<Paste the verbatim stack trace, error body, console error, or log lines. Do not
paraphrase and do not trim the frames. If there is no error text — a wrong value
rather than a failure — paste the actual observed output here instead and say so.>
```

## Reproduction

- Command: `<the single argv-runnable command that reproduces this, exactly as it must be run; its exit code must be non-zero while the bug is present and zero once fixed — use curl --fail only when the correct response is 2xx>`

<Use numbered steps INSTEAD of the Command line only when no single command can
reproduce it (a multi-screen UI journey). Delete the Command line if you do, and
give at least two steps:>

1. <first step>
2. <second step>

## Environment

- Repository / branch: <repo — branch>
- Version or commit: <tag, version, or commit sha the bug was observed on>
- Runtime / OS: <e.g. .NET 8 on Windows 11, Node 20 on Ubuntu 24.04>
- How it was run: <e.g. `dotnet run` against the local Dev DB>

## Regression

- Regression: <yes | no>
- Last known good: <commit, tag, or date — required when Regression is yes>

## Affected surface

- Surface: <api | ui | both>
- Runtime observable: <yes | no>
