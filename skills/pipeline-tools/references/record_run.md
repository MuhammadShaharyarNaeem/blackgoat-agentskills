# record_run.py — reference

Depth for the `record_run.py` section of `../SKILL.md`: the `--from-json` mapping table, what is deliberately NOT mapped, and the self-test inventory.

## `--from-json` mapping

A runtime's completion payload is read for these fields — top level first, then a nested `usage` object. An explicit flag always overrides the payload.

| Record field | Payload keys tried, in order |
|---|---|
| `tokens_in` | `tokens_in`, `input_tokens`, `prompt_tokens`, `inputTokens` |
| `tokens_out` | `tokens_out`, `output_tokens`, `completion_tokens`, `outputTokens` |
| `tokens_total` | `tokens_total`, `total_tokens`, `subagent_tokens`, `totalTokens` |
| `duration_s` | `duration_s`, `duration_seconds`, `durationSeconds`; else `duration_ms`, `durationMs`, `elapsed_ms`, `total_duration_ms` ÷ 1000 |
| `agent` | `agent`, `agent_name`, `subagent_type`, `subagentType` |
| `model` | `model`, `model_id`, `modelId` |
| `unit` | `unit`, `milestone` |
| `rounds` | `rounds` |
| `status` | `status`, and only if it is in the allowed set |

## Deliberately NOT mapped

- **Cache tokens** (`cache_creation_input_tokens`, `cache_read_input_tokens`): folding them into `tokens_in` is a pricing judgment, and this script records cost inputs, not a price.
- **Booleans**: a `True` coerced to `1` would fabricate a count.
- **`num_turns`**: a runtime turn is not a fix round. `rounds` means builder↔verifier cycles, and conflating the two would make the rounds column mean two different things across runtimes.

`tokens_total` is derived only from two known halves — one known half plus one unknown yields `null`, never the known half alone.

## Encoding and failure behavior

The log file is UTF-8 with `ensure_ascii=False`, so a note carrying an em dash or a non-Latin milestone title round-trips intact. The stdout report is ASCII only, for cp1252 console safety.

A failed write is **exit 2, not a warning** — a deliberate divergence from the best-effort gate ledger (convention #8). The ledger is an audit trail for later gates, so losing one line degrades a signal; here the record IS the artifact, and a silently dropped record is the whole telemetry surface going quiet.

## A verifier never runs below the producer it judges

The agent-audit's model-assignment-fit heuristic ("a verifier never runs below the producer it judges") was a finding a human read after the fact. The run log already held the evidence — one delegation record per agent, each carrying its tier — so this is where the finding becomes a refusal (convention #9).

On `--event delegation` with `--agent` in `quinn|luna|vera|cipher`, the script reads back the most recent **producer** delegation (`mason|nova|max`) in the **same `--unit`** and exits **1** with `verifier_below_producer` when this verifier's tier is lower. Tier order is `haiku < sonnet < opus`.

Three deliberate non-refusals, each of which would otherwise turn the check into noise:

- **An unknown tier is never compared.** The tier is matched by name appearing in the model string, so `claude-opus-4-1` resolves to `opus`; a value naming no tier, or two, resolves to `None` and the check stands down. Refusing on a guess about a model string this tool does not recognize is worse than not refusing — the same Evidence Integrity rule that makes an unmeasured token count `null` rather than `0`.
- **No producer in the unit yet is not an inversion.** A verifier legitimately runs first: the bugfix lane's pre-fix RED capture is Quinn before any builder.
- **Scoping is exact on `--unit`.** M2's cheap verifier is not judged against M1's opus builder; the comparison only means anything between a producer and the verifier of *that* work.

**`--allow-tier-inversion "<reason>"`** overrides it and records `"tier_inversion_reason"` on the record — an extra key, present only on an inverted record. An empty or whitespace-only reason is exit **2**: an inversion nobody justified in writing is precisely the one this check exists to stop, and a flag that accepts `""` is a flag that gets pasted in.

This introduces exit **1** to a script that previously had only 0 and 2. A refused delegation writes nothing.

## Self-test inventory

`python scripts/record_run.py --self-test` runs **31** cases: append plus parent-directory creation, unknowns staying `null`, an explicit `0` preserved, `tokens_total` derivation, field order, `--from-json` mapping including a nested `usage` object and the cache-token exclusion, an unmapped payload key leaving the field `null`, an explicit flag overriding the payload, a malformed and a missing `--from-json` file (exit 2), a missing required flag (exit 2), a bad `--event`/`--status`/count value (exit 2), a UTF-8 round trip, an unwritable path (exit 2), the four mandatory-`--model` cases, and the twelve tier-inversion cases (refused and blocking the write; equal and higher tiers passing; `--allow-tier-inversion` recording its reason; an empty reason as exit 2; a clean record carrying no inversion key; unit scoping; a verifier running first; latest-producer-wins; an unknown tier on either side; a full model id resolving to its tier; non-verifier and non-delegation records ungated; and the `model_tier` helper).
