# run_quiet.py — reference

Depth for the `run_quiet.py` section of `../SKILL.md`: the sidecar rationale, the stdout report shape, the built-in error profile, and the no-information-lost guarantee.

### Report shape (plain text on stdout)

```
command: dotnet test
exit code: 1
duration: 12.34s
full log: .docs/demo/implementation/logs/m3-tests.log
total lines: 842

ERROR EXCERPT (context +/-5 lines):
201: Assert.Equal() Failure
202: Expected: 200
203: Actual: 404
...
... 3 further match(es) omitted (cap ~200 excerpt lines) -- see full log: .docs/demo/implementation/logs/m3-tests.log

TAIL (last 15 lines):
828: Failed!  - Failed: 2, Passed: 40, Skipped: 0
...
```

- The header always carries `command`, `exit code`, `duration`, `full log` (the `--log` path — cite this when pointing an agent at the full record), and `total lines`; a timed-out run adds a `TIMEOUT: exceeded <N>s limit; process tree killed` line.
- `ERROR EXCERPT` appears only when at least one line matches the built-in error profile. Matches are merged into `±context`-line windows (overlapping/touching windows combine into one), each rendered with `<line number>: <text>` prefixes; non-adjacent windows are separated by a lone `...` line. The excerpt is capped at roughly 200 lines total; once the cap would be exceeded, further windows are dropped and a summary line reports how many further matches were omitted and repeats the log path.
- On a clean run (`exit code: 0` and no error-profile matches) the body is simply `no errors detected` instead of an excerpt. On a non-zero exit with no error-profile match, neither `no errors detected` nor an excerpt is printed — the body is empty and the report is just the header followed by the tail.
- `TAIL (last N lines)` is always printed: the last `--tail` lines of the run, numbered the same way.
### Built-in error profile (condensed)

One combined, case-insensitive regex, grouped by the tool family it targets — word-boundaried so summary lines ("`0 Failed`", "`Tests: 3 failed`") match, not just raw error lines:

- **MSBuild/C#**: `error CS/MSB/NU/NETSDK<digits>` diagnostic codes; `": error "` (the generic compiler line shape).
- **Test failures (cross-runner)**: `Failed!` (dotnet test summary), `FAILED` (generic runner summary), `[FAIL]` (tap/pytest-style), `FAIL ` (jest file line), `Error Message:` (xUnit/NUnit failure block), `Assert.` (assertion frame), `Expected:...Actual:` (assertion diff line, `.` matches across the line).
- **Node**: `ERR!` (npm error prefix), `✖` (mocha/jest failure mark).
- **Generic**: `exception`, `Traceback (most recent call last)` (Python), `fatal`.

### No-information-lost guarantee

The **full** log is always written to `--log`, unabridged, on every run — success or failure. The transcript (stdout) only ever loses *noise*, never *diagnostics*: the excerpt/tail selection narrows what appears in the agent's context window, not what's recoverable. When a failure needs more than the excerpt shows, grep the log file directly rather than re-running the command.

## The sidecar — why `--capture` alone was not enough

This is the half of `--capture` that a reader cannot forge by typing carefully. Owning the load-bearing *fields* stopped an agent from writing `Exit code: 0` over a failure; it did nothing about a capture authored end-to-end, because a hand-typed artifact and an observed one are the same bytes. The sidecar is written by the tool, names the process that ran, and hashes the artifact — so a capture with no sidecar was never produced by a probe, and one whose `capture_sha256` no longer matches was edited after the fact. `check_runtime_evidence.py` requires it.

### The body witnesses the sidecar

The sidecar closed the hand-typed-capture hole and left a narrower one: `capture_sha256` protects the capture FILE's bytes, and **nothing protects the sidecar's own fields**. Flipping a sidecar's `exit_code` from 3 to 0, or pushing its `finished` forward to defeat a downstream freshness or ordering check, is a one-line edit that leaves every hash intact — and it passed every gate, including one where the capture's own body read `- Exit code: 3` two lines above the fence.

So the two records are deliberately redundant, and the hash-protected one is the witness: `- Exit code:` is rendered from the same value the sidecar records, and `- Captured:` is rendered from the sidecar's `finished` instant **exactly** (it used to call `now()` again while rendering, which left the pair honestly but unpredictably a second apart — an inconsistency no downstream gate could tell from tampering). `assert_capture_agrees()` re-checks the pair before the sidecar is written, so this tool cannot be the source of a capture that fails the agreement contract in `../SKILL.md`: a gate reporting `sidecar_body_disagrees` is reporting an edit, not a race.

**Cross-platform caveat:** `capture_sha256` is over raw bytes, and git's `core.autocrlf` rewrites line endings on checkout. A capture committed from one platform and checked out on another will fail its own hash. Mark the evidence directory `-text` in `.gitattributes` (the shipped fixtures under `fixtures/runtime-evidence-*/` each carry one) or keep captures out of version control.
