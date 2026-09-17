# check_redelegation.py — reference

Depth for `check_redelegation.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show check_redelegation`); this page holds only the reasoning behind it.

## The measurement behind it

On one audited epic, Quinn was delegated four times against the same milestone and returned PARTIAL every time with the same blocker: no admin shell, no installed service, no dev token. It was an environment wall only the human could clear. Roughly 1.2M tokens were spent re-discovering that one fact, once per round, because each round began with a fresh agent that could not know the previous three had hit the same wall.

`orchestrator-contract.md` §2 already said to halt after three consecutive attempts. It was in force the whole time. CLAUDE.md convention #9 is the response: a rule that asks the Orchestrator to stop at the moment it most wants to proceed — a fresh agent is cheap, and the next round *feels* like it might land — becomes a gate, not louder prose.

## Why a standing halt short-circuits everything

Once a halt is recorded against a unit, it is reported verbatim on every later run against that unit, whatever the new handoff says, and the other rules are not evaluated. The reason is that the halt is a claim about the unit's **world**, not about the handoff that happened to trigger it. A different agent, or the same agent on a better-worded round, can produce a clean-looking handoff without anything in the environment having changed.

That is also why **this gate never clears a halt, on any result**. A passing re-run is exactly what a halt looks like from the inside. Lifting one is a human act with a recorded reason, performed through `update_state.py --clear-halt`, which requires that reason — the write path deliberately refuses to let a passing re-run flip the field.

## Why the categories split the way they do

The `blocked_on:` categories come from `check_handoff.py`'s grammar, and this gate reads them as a statement about who can act:

- **environment** and **credentials** are outside the agent's power entirely. No re-delegation can clear them, so they halt for the user with no waiver — a flag that waived them would be a flag for re-running the thing that cannot work.
- **dependency** is usually outside the agent's power but sometimes genuinely changes between rounds (the dependency shipped, the other team merged). So it halts by default and is waivable in writing, with the reason recorded on the ledger line — the same hand-typed-waiver pattern the family uses wherever no script can judge the justification.
- **spec** and **defect** are inside the loop's power to resolve, so neither halts on its own. They are what a fix round is *for*.

## Why repetition is two independent checks

The **round bound** is the mechanical form of the contract's three-attempt rule and is applied unconditionally. It is deliberately not suppressed by supplying the previous handoff: the failure mode being closed is a fourth round let through because this round's *wording* differed, and a bound that a caller can disarm by passing an extra flag is not a bound.

The **similarity** check is layered on top and needs the previous handoff to compare against. It can trip a round earlier than the bound would, because two blockers that are the same blocker in different words are already the loop this exists to stop. Both may fire at once; they answer different questions — "how many times has this failed?" and "is it failing for the same reason?" — and collapsing them into one would lose whichever answer the other happened to reach first.

## Scope limits

- It counts records in the run log. A delegation nobody recorded is invisible to it, which is why `record_run.py` refuses an unmeasured delegation in the first place.
- The similarity measure is lexical over the blockers text. Two genuinely different blockers described in the same vocabulary will score high; a human reads the reported similarity and the two handoffs before acting on it.
- A halt write that fails is a warning on this gate's own report, never a change to its verdict — the verdict is about the delegation, not about whether the state file could be updated.
