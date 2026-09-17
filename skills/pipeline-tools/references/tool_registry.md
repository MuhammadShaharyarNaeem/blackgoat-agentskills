# tool_registry.py — reference

Depth for `tool_registry.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show tool_registry`); this page holds only the reasoning behind it.

## Why the spine stopped carrying per-script contracts

`pipeline-tools/SKILL.md` used to restate every script's synopsis, flags, JSON keys, exit codes and problem codes. Two costs followed from that, and both were paid repeatedly:

- **It drifted.** A restatement of a contract is a second copy of it, maintained by hand, and the copy lost. Counts went stale, flags were added to a script and never to the page, and a reader who trusted the page typed a flag the script did not have.
- **It was read whole to answer one question.** An agent needing one flag's exact name loaded tens of thousands of words of contract for thirty-odd other scripts.

The script's own `--help` has neither problem: it is generated from the argument parser and the script's own epilog, so it cannot describe a flag that does not exist, and it is one script's worth of text. It is now the contract of record. `registry.json` carries only what `--help` cannot: which agents and lanes a tool belongs to, and why a carve-out exists.

This is a **deliberate refinement of CLAUDE.md convention #1** (convention #8): the per-script contract lives in the script, not the spine. It is not a shadow contract — there is exactly one contract per script, and it is executable.

## The four commands

`list` is the index. `show <name>` is how an agent reads a contract — the registry entry, then that script's `--help` verbatim. `for --agent <name>` and `for --lane <lane>` are the routing questions: which tools is this agent permitted to run, and which does this lane use. `--verify` checks the registry against reality.

`for --agent` answers *permission*, not *availability*. The spine's *Single contract authority* section states the rule — the gates that decide whether work is done are the Orchestrator's, and an agent runs only the self-gating captures and lints it applies to its own output before handing anything back. Each carve-out entry carries the reason it exists, so the answer arrives with its justification rather than as a bare list.

## `--verify`, and what it is a conversion of

The old arrangement enforced the shape of a contract with prose: a section was supposed to carry a synopsis, its flags, its JSON keys, its exit codes and its problem codes, and whether it did was checked by whoever happened to read it. That is precisely the rule CLAUDE.md convention #9 says to convert — compliance is a count, and the moment it is skipped is the moment somebody is shipping a new script.

`--verify` is that conversion. It runs every registered script's `--help`, asserts the registry names a file that exists, that every script in the directory is registered, that the registry's description is the help's own first line, and that the help carries its mandatory epilog headings. A drifting description or a missing exit-codes section is now an exit code rather than a reading someone did not do.

The pairing runs in both directions on purpose: an entry naming a missing script and a script with no entry are different failures, and only checking one of them leaves the other free.
