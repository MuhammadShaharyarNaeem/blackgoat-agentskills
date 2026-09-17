# check_agent_originality.py — reference

Depth for `check_agent_originality.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show check_agent_originality`); this page holds only the reasoning behind it.

## What it is for

The `agent-audit` skill's DRY metric asks whether two personas or two methodology skills are really the same document wearing different names. Read by eye, a re-skin is invisible: the agent names differ, the stack words differ, and the reader's attention goes to those differences rather than to the eight-word runs of prose that are identical underneath. This script is that metric's mechanical half, ported from the `agency-agents` project's shell original.

## Why entities are neutralized before scoring

Scoring raw text measures the wrong thing in both directions. A genuine duplicate that swapped agent names and stack words scores *low*, because the swapped tokens break every shingle that contains one; and two genuinely different skills that both carry this tree's shared boilerplate score *high* on that boilerplate alone.

So three classes of text are neutralized before any shingle is taken:

- **this tree's agent names and stack words**, which is what a re-skin changes and nothing else;
- **CLAUDE.md convention #10's Quick card disclaimer and inline mapping**, which the convention requires to be verbatim across every skill that carries a card — text mandated to be identical cannot be evidence of copying;
- **the `## Worker Execution Contract` heading**, for the same reason.

Without those exclusions the shared boilerplate would manufacture overlap between unrelated skills and, by raising the floor everywhere, hide the real pair.

## Why the two groups are never compared

An agent persona and a methodology skill are different documents with different jobs — WHO versus HOW (CLAUDE.md convention #4). Their vocabularies overlap by design, so a cross-group score measures the plugin's house style, not duplication. Every pair is scored **within** its own group only.

## Thresholds

The fail and warn percentages are calibrated against this tree's own worst *genuine* pair — the highest score between two documents that are legitimately distinct — leaving a wide margin above it. That is deliberate: a threshold set just above the observed floor turns every ordinary edit into an audit finding, and a metric that fires constantly is a metric nobody reads. The numbers themselves live in the `--help`, because they move when the tree does.

## `agents/blackgoat.md`

It is compared, so its scores appear in the report, but a pair naming it can never fail or warn: it is the human author's psychological profile, exempt by design from every agent-audit metric (CLAUDE.md convention #7). Its row reads as not-applicable by design rather than being silently dropped — a file missing from the report is indistinguishable from a file the tool failed to read.

## Scope limits

- Overlap is **lexical**. Two documents that say the same thing in different words score zero, and this script makes no claim about them; that judgement is the audit's Role Cohesion lens, read by a human.
- A high score is a **finding to investigate**, not a verdict. Two skills that legitimately share a long quoted contract will score high and be correct to.
