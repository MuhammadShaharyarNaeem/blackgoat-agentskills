# diff_findings.py — reference

Depth for `diff_findings.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show diff_findings`); this page holds only the reasoning behind it.

## What it answers

After a rescan, the question is not "how many findings are there" but "which of last round's findings are gone, which are still here, and what is new". Read by eye across two long reports that is a manual diff of prose, and the answer it usually produces is the flattering one: the reviewer recognises the findings they remember fixing and does not notice the one that quietly persisted under a reworded title.

## Why the fingerprint is `check_agent_report.py`'s, not its own

The fingerprint is defined and emitted by `check_agent_report.py --emit-fingerprints`, and this tool consumes it. Two tools deriving "the same finding" independently is two definitions that drift, and the drift would be invisible: a rename in one and not the other turns a PERSISTENT finding into a RESOLVED one plus a NEW one, which is exactly the misreading the tool exists to prevent.

The properties that matter here, and why each one is part of the key:

- **The line number is excluded.** A fix landing *above* a finding shifts it down the file. Keyed on location, that finding would be reported as resolved and immediately re-reported as new, and a reader who trusts the RESOLVED column would be reading a fix that never happened.
- **Digit runs are collapsed and whitespace normalised.** A reworded count or a re-wrapped line is the same finding.
- **The category comes from the nearest preceding check line**, because the finding grammar carries no category of its own — the finding's position under a check is what says which check found it.

Matching is by fingerprint alone and never by position: a finding that only moved is PERSISTENT.

## Why only each report's gated section is read

Cipher appends one section per round and never edits an earlier one. Reading the whole file would therefore find every finding ever raised still present in the text, so a fixed finding would look permanently unresolved and the RESOLVED column would always be empty. Each report contributes only its own latest verdict-bearing section — the same section `check_agent_report.py` grades.

## Why it does not gate by default

The classification is a reading aid, and which classification should stop a lane is the caller's decision, not this tool's: a new finding blocks a security sign-off but is expected output of a first rescan after a large change, and a persistent finding may be one somebody already triaged and accepted. So the default exits 0 whatever the classification, the table prints regardless of exit code, and the two opt-in flags are how a pipeline step says which column it is willing to fail on.
