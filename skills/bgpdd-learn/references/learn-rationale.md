# Learning Triage — Rationale

On-demand companion to the `bgpdd-learn` SKILL.md. The operational contract lives in the spine; this file carries the reasoning behind two of its rules. Not needed to execute the skill.

## Why the skill exists

Every working session generates lessons — user corrections, agent failures, friction that repeats — and most of them evaporate when the session ends. This skill captures them on demand and routes each one to the layer where it belongs, instead of leaving the learning to whoever happens to remember it next time.

## Why Step 1 records confirmations, not only failures

A decision or rule that a later phase confirmed worked cleanly is evidence too: it identifies which rules are earning their keep and must be protected from future pruning or "simplification".

An evidence brief composed only of failures teaches the next optimization pass to delete the rules that were quietly working, and gives Forge no way to distinguish a load-bearing rule from dead weight. The optimization loop then oscillates — a rule is added after it is missed, removed as unused noise once it is doing its job silently, and re-added after the next failure it would have prevented.

## Why Step 2 must inject `{PLUGIN_ROOT}` explicitly

Forge is a spawned subagent and cannot compute his own on-disk location. Without that path injected he must either guess or scan the filesystem to reach his own methodology and the destination files — and his Path Resolution rule forbids both. The Orchestrator is the only actor in the loop that knows where the plugin lives, so the resolution has to happen there and travel in the brief.
